import os
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
from concurrent.futures import ProcessPoolExecutor, as_completed

print(f"🚀 Posture analyzer started on {socket.gethostname()}")

# Database connection (main process only)
conn = psycopg2.connect(
    host=os.environ['SUPABASE_HOST'],
    database=os.environ['SUPABASE_DB'],
    user=os.environ['SUPABASE_USER'],
    password=os.environ['SUPABASE_PASSWORD'],
    port=os.environ.get('SUPABASE_PORT', 5432),
    sslmode=os.environ.get('SUPABASE_SSL', 'require')
)
cursor = conn.cursor()

# MQTT and folder setup
broker = '192.168.1.79'
port = 1883
output_base = './analyzed_images'

NUM_COPIES = 100
NUM_WORKERS = max(1, os.cpu_count() or 4)

font = cv2.FONT_HERSHEY_SIMPLEX
colors = {
    "blue": (255, 127, 0),
    "red": (50, 50, 255),
    "green": (127, 255, 0),
    "light_green": (127, 233, 100),
    "yellow": (0, 255, 255),
    "pink": (255, 0, 255)
}

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

def findDistance(x1, y1, x2, y2):
    return m.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

def findAngle(x1, y1, x2, y2):
    try:
        a = [x1, y1]; b = [x2, y2]; vertical = [x1, y1 - 100]
        ab = [b[0] - a[0], b[1] - a[1]]
        av = [vertical[0] - a[0], vertical[1] - a[1]]
        dot = ab[0] * av[0] + ab[1] * av[1]
        mag_ab = m.sqrt(ab[0]**2 + ab[1]**2)
        mag_av = m.sqrt(av[0]**2 + av[1]**2)
        angle_rad = m.acos(dot / (mag_ab * mag_av))
        return int(m.degrees(angle_rad))
    except:
        return 0

def analyze_and_save(copy_idx, img_bgr, w, h, prefix, unique_id, output_folder):
    global _pose, _mp_pose, _mp_drawing, _mp_styles
    image = img_bgr.copy()
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    keypoints = _pose.process(image_rgb)

    neck_angle = None
    body_angle = None
    posture_status = "Unknown"
    landmarks_detected = False

    if keypoints.pose_landmarks:
        lm = keypoints.pose_landmarks
        lmPose = _mp_pose.PoseLandmark
        required = [
            lmPose.LEFT_SHOULDER, lmPose.RIGHT_SHOULDER,
            lmPose.LEFT_HIP, lmPose.RIGHT_HIP,
            lmPose.LEFT_EAR, lmPose.NOSE, lmPose.LEFT_KNEE
        ]
        is_valid = all(lm.landmark[lid].visibility >= 0.01 for lid in required)
        visible_landmarks = [l for l in lm.landmark if l.visibility >= 0.9]

        if len(visible_landmarks) >= 20 and is_valid:
            _mp_drawing.draw_landmarks(
                image, lm, _mp_pose.POSE_CONNECTIONS,
                landmark_drawing_spec=_mp_styles.get_default_pose_landmarks_style()
            )
            l_shldr = lm.landmark[lmPose.LEFT_SHOULDER]
            r_shldr = lm.landmark[lmPose.RIGHT_SHOULDER]
            l_ear = lm.landmark[lmPose.LEFT_EAR]
            l_hip = lm.landmark[lmPose.LEFT_HIP]
            l_knee = lm.landmark[lmPose.LEFT_KNEE]

            l_shldr_x, l_shldr_y = int(l_shldr.x * w), int(l_shldr.y * h)
            r_shldr_x, r_shldr_y = int(r_shldr.x * w), int(r_shldr.y * h)
            l_ear_x, l_ear_y = int(l_ear.x * w), int(l_ear.y * h)
            l_hip_x, l_hip_y = int(l_hip.x * w), int(l_hip.y * h)
            l_knee_x, l_knee_y = int(l_knee.x * w), int(l_knee.y * h)

            neck_angle = findAngle(l_shldr_x, l_shldr_y, l_ear_x, l_ear_y)
            body_angle = findAngle(l_hip_x, l_hip_y, l_shldr_x, l_shldr_y)

            posture_ok = 10 < neck_angle < 50 and body_angle < 20
            posture_status = "Good" if posture_ok else "Bad"
            landmarks_detected = True

            color = colors["light_green"] if posture_ok else colors["red"]
            cv2.putText(image, f'Neck: {neck_angle}°  Body: {body_angle}°', (10, 60), font, 0.9, color, 2)
            if not posture_ok:
                cv2.putText(image, "Bad_Posture", (10, h - 30), font, 1, colors["red"], 3)
        else:
            posture_status = "Partial_Landmarks_Detected"
            cv2.putText(image, "Full human not detected", (30, 50), font, 1, colors["red"], 2)
    else:
        posture_status = "No_Landmarks_Detected"
        cv2.putText(image, "No landmarks detected", (30, 50), font, 1, colors["red"], 2)

    filename = f"{prefix}_{unique_id}_{copy_idx+1}.jpg"
    save_path = os.path.join(output_folder, filename)
    cv2.imwrite(save_path, image)

    return {
        "filename": filename,
        "neck_angle": neck_angle,
        "body_angle": body_angle,
        "posture_status": posture_status,
        "landmarks_detected": landmarks_detected
    }

_pool = ProcessPoolExecutor(max_workers=NUM_WORKERS, initializer=_worker_init)

def on_connect(client, userdata, flags, rc):
    print(f"Connected with result code {rc}")
    client.subscribe("images/pi1_3")

def on_message(client, userdata, msg):
    try:
        image_data = base64.b64decode(msg.payload)
        np_arr = np.frombuffer(image_data, np.uint8)
        original_image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if original_image is None:
            print("Could not decode image.")
            return

        topic_parts = msg.topic.split('/')
        prefix = topic_parts[1] if len(topic_parts) > 1 else "unknown"
        output_folder = os.path.join(output_base, f'analyzed_images_from_{prefix}')
        os.makedirs(output_folder, exist_ok=True)

        h, w = original_image.shape[:2]
        unique_id = random.randint(10000, 99999)
        received_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hostname = socket.gethostname()

        futures = [
            _pool.submit(analyze_and_save, i, original_image, w, h, prefix, unique_id, output_folder)
            for i in range(NUM_COPIES)
        ]

        for idx, f in enumerate(as_completed(futures), 1):
            try:
                result = f.result()
                analyzed_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                cursor.execute(
                    "INSERT INTO posture_log (pi_id, filename, received_time, analyzed_time, neck_angle, body_angle, posture_status, landmarks_detected, processed_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (prefix, result['filename'], received_time, analyzed_time, result['neck_angle'], result['body_angle'], result['posture_status'], result['landmarks_detected'], hostname)
                )
                conn.commit()

                print(f"✅ [{idx}/{NUM_COPIES}] Saved and logged: {result['filename']} :: {result['posture_status']}")
            except Exception as e:
                print(f"❌ DB Insert Error: {e}")

    except Exception as e:
        print(f"❌ Error processing message: {e}")

# MQTT setup
client = mqtt.Client(protocol=mqtt.MQTTv311)
client.on_connect = on_connect
client.on_message = on_message
print("✅ Connected to MQTT broker")
client.connect(broker, port, 60)
client.loop_forever()

