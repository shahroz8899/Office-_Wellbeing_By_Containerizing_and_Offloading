import os
import sys
import cv2
import base64
import random
import math as m
import numpy as np
import paho.mqtt.client as mqtt
import psycopg2
from datetime import datetime
import mediapipe as mp
import socket
import logging
import queue
from concurrent.futures import ProcessPoolExecutor, as_completed
import subprocess
import threading
import re

# ---------------------------
# Config (env overrides)
# ---------------------------
BROKER = os.environ.get("MQTT_BROKER", "192.168.1.79")
PORT = int(os.environ.get("MQTT_PORT", "1883"))
TOPIC = os.environ.get("MQTT_TOPIC", "images/#")
OUTPUT_BASE = os.environ.get("OUTPUT_DIR", "./analyzed_images")

_default_workers = os.cpu_count() or 4
NUM_WORKERS = int(os.environ.get("NUM_WORKERS", str(max(1, _default_workers))))

# DB (can disable via DB_ENABLED=false)
DB_HOST = os.environ.get("DB_HOST", "aws-0-eu-north-1.pooler.supabase.com")
DB_NAME = os.environ.get("DB_NAME", "postgres")
DB_USER = os.environ.get("DB_USER", "postgres.yvqqpgixkwsiychmwvkc")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "University12@")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_SSLMODE = os.environ.get("DB_SSLMODE", "require")
DB_ENABLED = os.environ.get("DB_ENABLED", "false").lower() == "true"

COPIES_SCHEDULE = [100 * i for i in range(1, 11)]  # 10,20,...,100
CSV_PATH = os.environ.get("CSV_PATH", "pi1_8.csv")

# ---------------------------
# Logging
# ---------------------------
LOGGER = logging.getLogger("posture_bm_one_per_loop")
LOGGER.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
LOGGER.addHandler(_sh)

os.makedirs(OUTPUT_BASE, exist_ok=True)
LOGGER.info("🚀 Starting benchmark on %s | MQTT %s:%s | topic=%s | workers=%s",
            socket.gethostname(), BROKER, PORT, TOPIC, NUM_WORKERS)

# ---------------------------
# DB
# ---------------------------
conn = None
cursor = None

def ensure_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS posture_log (
            id SERIAL PRIMARY KEY,
            pi_id TEXT,
            filename TEXT,
            received_time TIMESTAMP,
            analyzed_time TIMESTAMP,
            neck_angle INT,
            body_angle INT,
            posture_status TEXT,
            landmarks_detected BOOLEAN,
            processed_by TEXT
        );
        """
    )

def connect_db():
    global conn, cursor
    if not DB_ENABLED:
        LOGGER.warning("DB disabled via DB_ENABLED=false; skipping DB writes.")
        return
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT,
            sslmode=DB_SSLMODE,
        )
        cursor = conn.cursor()
        ensure_table(cursor)
        conn.commit()
        LOGGER.info("✅ DB connected and table ensured.")
    except Exception as e:
        LOGGER.error("❌ DB connection failed: %s", e)
        LOGGER.warning("Continuing without DB writes.")
        conn = None
        cursor = None

connect_db()

# ---------------------------
# Per-process state (for workers)
# ---------------------------
font = cv2.FONT_HERSHEY_SIMPLEX
colors = {
    "light_blue": (255, 200, 100),
    "light_green": (127, 233, 100),
    "yellow": (0, 255, 255),
    "pink": (255, 0, 255)
}

# globals for worker processes (initialized in _worker_init)
_pose = None
_mp_pose = None
_mp_drawing = None
_mp_styles = None

def _worker_init():
    global _pose, _mp_pose, _mp_drawing, _mp_styles
    _mp_pose = mp.solutions.pose
    _pose = _mp_pose.Pose(static_image_mode=True, model_complexity=2)
    _mp_drawing = mp.solutions.drawing_utils
    _mp_styles = mp.solutions.drawing_styles

# ---------------------------
# Utilities
# ---------------------------
def findDistance(x1, y1, x2, y2):
    return m.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

def findAngle(x1, y1, x2, y2):
    try:
        a = [x1, y1]; b = [x2, y2]; vertical = [x1, y1 - 100]
        ab = [b[0] - a[0], b[1] - a[1]]
        av = [vertical[0] - a[0], vertical[1] - a[1]]
        dot = ab[0] * av[0] + ab[1] * av[1]
        mag_ab = m.sqrt(ab[0] ** 2 + ab[1] ** 2)
        mag_av = m.sqrt(av[0] ** 2 + av[1] ** 2)
        if mag_ab == 0 or mag_av == 0:
            return 0
        cosang = max(-1.0, min(1.0, dot / (mag_ab * mag_av)))
        ang = m.degrees(m.acos(cosang))
        return int(ang)
    except Exception:
        return 0

def decode_image(payload: bytes):
    # try base64 first
    try:
        data = base64.b64decode(payload, validate=True)
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            return img, "base64"
    except Exception:
        pass

    # try raw bytes
    try:
        img = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            return img, "raw"
    except Exception:
        pass

    return None, "unknown"

def analyze_and_save(copy_idx, img_bgr, w, h, prefix, unique_id, output_folder):
    # Copy & prepare
    result = {
        "saved": False,
        "filename": None,
        "neck_angle": None,
        "body_angle": None,
        "posture_status": "Unknown",
        "landmarks_detected": False
    }
    try:
        image = img_bgr.copy()
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        res = _pose.process(image_rgb)
        neck_angle = 0
        body_angle = 0
        posture_status = "Unknown"

        if res.pose_landmarks:
            lms = res.pose_landmarks.landmark
            # required landmarks by index
            idx = {
                "left_shoulder": 11, "right_shoulder": 12,
                "left_hip": 23, "right_hip": 24,
                "left_ear": 7, "right_ear": 8,
                "left_knee": 25, "right_knee": 26
            }
            required = [idx["left_shoulder"], idx["left_hip"], idx["left_ear"]]
            vis_ok = True
            for i in required:
                try:
                    if lms[i].visibility < 0.01:
                        vis_ok = False
                        break
                except Exception:
                    vis_ok = False
                    break

            # additional criterion: >=20 landmarks with visibility >=0.9
            high_vis = sum(1 for lm in lms if getattr(lm, "visibility", 0.0) >= 0.9)
            if vis_ok and high_vis >= 20:
                _mp_drawing.draw_landmarks(
                    image,
                    res.pose_landmarks,
                    _mp_pose.POSE_CONNECTIONS,
                    landmark_drawing_spec=_mp_styles.get_default_pose_landmarks_style()
                )

                def _pix(lm):
                    return int(lm.x * w), int(lm.y * h)

                ls = lms[idx["left_shoulder"]]
                le = lms[idx["left_ear"]]
                lh = lms[idx["left_hip"]]

                lsx, lsy = _pix(ls)
                lex, ley = _pix(le)
                lhx, lhy = _pix(lh)

                neck_angle = findAngle(lsx, lsy, lex, ley)
                body_angle = findAngle(lhx, lhy, lsx, lsy)

                posture_status = "Good" if (10 < neck_angle < 50 and body_angle < 20) else "Bad"

                cv2.putText(image, f"Neck Angle: {neck_angle} deg", (10, 30), font, 1, colors["light_blue"], 2)
                cv2.putText(image, f"Body Angle: {body_angle} deg", (10, 70), font, 1, colors["light_green"], 2)

                if posture_status == "Bad":
                    cv2.putText(image, "Bad_Posture", (10, 110), font, 1, colors["pink"], 2)
                result["landmarks_detected"] = True
            else:
                cv2.putText(image, "Insufficient landmarks/visibility", (10, 30), font, 1, colors["yellow"], 2)
                posture_status = "Insufficient_Landmarks"
        else:
            cv2.putText(image, "No pose landmarks detected", (10, 30), font, 1, colors["yellow"], 2)
            posture_status = "No_Landmarks"

        fname = f"{prefix}_{unique_id}_{copy_idx + 1}.jpg"
        fpath = os.path.join(output_folder, fname)
        ok = cv2.imwrite(fpath, image)

        result.update({
            "saved": bool(ok),
            "filename": fname if ok else None,
            "neck_angle": neck_angle,
            "body_angle": body_angle,
            "posture_status": posture_status
        })
    except Exception as e:
        # keep result fields as default; log
        LOGGER.exception("analyze_and_save error: %s", e)
    return result

# ---------------------------
# MQTT
# ---------------------------
message_q: "queue.Queue[tuple[str, np.ndarray, datetime]]" = queue.Queue()

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        LOGGER.info("✅ Connected to MQTT; subscribing to %s", TOPIC)
        client.subscribe(TOPIC)
    else:
        LOGGER.error("❌ MQTT connection failed with rc=%s", rc)

def on_message(client, userdata, msg):
    # push every message; main loop will take exactly one per loop
    try:
        received_time = datetime.now()
        img, enc = decode_image(msg.payload)
        if img is None:
            LOGGER.error("Could not decode image from %s (enc=%s)", msg.topic, enc)
            return
        message_q.put((msg.topic, img, received_time))
    except Exception as e:
        LOGGER.exception("on_message error: %s", e)


# ---------------------------
# Resource Sampler (tegrastats)
# ---------------------------
class ResourceSampler:
    """
    Samples GPU/CPU/RAM% from `tegrastats` while running.
    - GPU:  GR3D_FREQ X%
    - CPU:  average of all core samples like '5%@', '12%@', ...
    - RAM:  RAM used/totalMB|MiB|GB|GiB -> used/total * 100
    """
    def __init__(self, interval_ms: int = 200):
        self.interval_ms = interval_ms
        self.proc = None
        self.thread = None
        self.stop_event = threading.Event()
        self._gpu = []
        self._cpu = []
        self._ram = []

        # compiled regexes for speed
        self.re_gpu = re.compile(r"GR3D_FREQ\s+(\d+)%")
        self.re_cpu_all = re.compile(r"(\d+)%@")
        # RAM used/total with units MB/MiB/GB/GiB; we normalize to percent
        self.re_ram = re.compile(r"RAM\s+(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)(?:\s*)([MG]i?B)")

    def _reader(self, pipe):
        try:
            for raw in iter(pipe.readline, ''):
                if self.stop_event.is_set():
                    break
                line = raw.strip()

                # GPU %
                m_gpu = self.re_gpu.search(line)
                if m_gpu:
                    try:
                        self._gpu.append(float(m_gpu.group(1)))
                    except Exception:
                        pass

                # CPU % (avg across all cores present in the line)
                cpu_matches = self.re_cpu_all.findall(line)
                if cpu_matches:
                    try:
                        core_vals = [float(v) for v in cpu_matches]
                        if core_vals:
                            self._cpu.append(sum(core_vals) / len(core_vals))
                    except Exception:
                        pass

                # RAM % (used/total * 100)
                m_ram = self.re_ram.search(line)
                if m_ram:
                    try:
                        used = float(m_ram.group(1))
                        total = float(m_ram.group(2))
                        # unit = m_ram.group(3).lower()  # ratio independent of unit (tegrastats uses same unit)
                        if total > 0:
                            self._ram.append((used / total) * 100.0)
                    except Exception:
                        pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def start(self):
        try:
            self.proc = subprocess.Popen(
                ["tegrastats", "--interval", str(self.interval_ms)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            # tegrastats not present – operate as a no-op sampler
            self.proc = None
            LOGGER.warning("tegrastats not found; resource sampling disabled for this run.")
            return self

        self.thread = threading.Thread(target=self._reader, args=(self.proc.stdout,), daemon=True)
        self.thread.start()
        return self

    def stop_and_summary(self):
        # stop the reader
        self.stop_event.set()
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
        if self.thread:
            try:
                self.thread.join(timeout=1.5)
            except Exception:
                pass
        if self.proc:
            try:
                self.proc.wait(timeout=1.5)
            except Exception:
                pass

        def _avg(vals):
            return round(sum(vals) / len(vals), 6) if vals else None

        return {
            "avg_gpu_pct": _avg(self._gpu),
            "avg_cpu_pct": _avg(self._cpu),
            "avg_ram_pct": _avg(self._ram),
        }

# ---------------------------
# Main
# ---------------------------
def write_csv(rows):
    import csv
    headers = ["loop_index", "copies_in_loop", "processed_count", "avg_process_time_seconds",
               "pi_id", "loop_received_time", "avg_gpu_pct", "avg_cpu_pct", "avg_ram_pct"]
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    LOGGER.info("🧾 Wrote CSV: %s", CSV_PATH)

def main():
    hostname = socket.gethostname()
    pool = ProcessPoolExecutor(max_workers=NUM_WORKERS, initializer=_worker_init)

    client = mqtt.Client(protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        LOGGER.info("Connecting to MQTT %s:%s ...", BROKER, PORT)
        client.connect(BROKER, PORT, 60)
    except Exception as e:
        LOGGER.error("❌ MQTT connect failed: %s", e)
        pool.shutdown(wait=False, cancel_futures=True)
        return

    client.loop_start()

    rows = []

    try:
        for loop_idx, copies in enumerate(COPIES_SCHEDULE, start=1):
            LOGGER.info("⏩ Loop %d/10: waiting for ONE MQTT image (copies=%d)...", loop_idx, copies)
            topic, image_bgr, received_time = message_q.get()  # block for one image
            # derive pi_id from topic
            parts = topic.split("/")
            pi_id = parts[1] if len(parts) > 1 else "unknown"

            # out dir
            output_folder = os.path.join(OUTPUT_BASE, f"analyzed_images_from_{pi_id}")
            os.makedirs(output_folder, exist_ok=True)

            h, w = image_bgr.shape[:2]
            unique_id = random.randint(10000, 99999)

            sampler = ResourceSampler(interval_ms=200).start()

            futures = [
                pool.submit(analyze_and_save, i, image_bgr, w, h, pi_id, unique_id, output_folder)
                for i in range(copies)
            ]

            total_time = 0.0
            finished = 0

            for f in as_completed(futures):
                try:
                    result = f.result()
                    analyzed_time = datetime.now()
                    proc_time = (analyzed_time - received_time).total_seconds()
                    total_time += proc_time
                    finished += 1

                    # Optional DB insert (one record per copy)
                    if cursor is not None:
                        try:
                            cursor.execute(
                                """
                                INSERT INTO posture_log
                                (pi_id, filename, received_time, analyzed_time, neck_angle, body_angle,
                                 posture_status, landmarks_detected, processed_by)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    pi_id,
                                    result.get("filename"),
                                    received_time,
                                    analyzed_time,
                                    result.get("neck_angle"),
                                    result.get("body_angle"),
                                    result.get("posture_status"),
                                    result.get("landmarks_detected"),
                                    hostname
                                )
                            )
                            conn.commit()
                        except Exception as db_e:
                            LOGGER.error("DB insert failed for %s: %s", result.get("filename"), db_e)
                except Exception as e:
                    LOGGER.error("Worker task failed: %s", e)

            loop_stats = sampler.stop_and_summary() if "sampler" in locals() and sampler else {"avg_gpu_pct": None, "avg_cpu_pct": None, "avg_ram_pct": None}
            avg_time = (total_time / finished) if finished else 0.0
            rows.append([loop_idx, copies, finished, round(avg_time, 6), pi_id,
                         received_time.strftime("%Y-%m-%d %H:%M:%S"),
                         loop_stats.get("avg_gpu_pct"), loop_stats.get("avg_cpu_pct"), loop_stats.get("avg_ram_pct")])

            LOGGER.info("✅ Loop %d done: processed=%d, avg_process_time=%.6fs | GPU%%=%s CPU%%=%s RAM%%=%s",
                        loop_idx, finished, avg_time,
                        loop_stats.get("avg_gpu_pct"), loop_stats.get("avg_cpu_pct"), loop_stats.get("avg_ram_pct"))

        # after all 10 loops
        write_csv(rows)

    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        pool.shutdown(wait=True, cancel_futures=True)
        if cursor is not None:
            try: cursor.close()
            except Exception: pass
        if conn is not None:
            try: conn.close()
            except Exception: pass

if __name__ == "__main__":
    main()
