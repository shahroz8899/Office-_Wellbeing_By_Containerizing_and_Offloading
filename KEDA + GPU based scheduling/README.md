# 📦 GPU-Aware KEDA-Based Posture Analyzer

This project enables intelligent posture analysis of images sent over MQTT, using GPU-optimized Kubernetes Jobs dynamically scheduled via [KEDA](https://keda.sh). It automatically selects the worker node with the lowest GPU load, triggers analysis jobs, and logs results to a PostgreSQL database.

---

## 🚀 Features

- 📡 Real-time posture image ingestion via MQTT
- 🧠 MediaPipe-based posture angle calculation
- 🔁 Autoscaling with KEDA using GPU metrics from Prometheus
- 🐳 Multi-arch Docker container (Jetson + x86_64)
- 🗃️ Logs results into Supabase PostgreSQL

---

## ⚙️ Prerequisites

### Software
- Docker with `buildx` plugin
- Kubernetes with KEDA installed
- Prometheus configured and scraping node GPU metrics
- Python 3.7+
- MQTT Broker (e.g., Mosquitto)
- PostgreSQL DB (e.g., Supabase)

### Python Requirements
Install with:
```bash
pip install -r requirements.txt
```

**requirements.txt**
```
opencv-python
mediapipe
paho-mqtt
numpy
matplotlib
psycopg2-binary
psutil
prometheus-api-client
keyboard
```

### Environment Variables
Set the following before running:
```
SUPABASE_HOST=
SUPABASE_DB=
SUPABASE_USER=
SUPABASE_PASSWORD=
```

---

## 📁 Folder Overview

| File                          | Purpose                                                  |
|------------------------------|----------------------------------------------------------|
| `build_and_push.py`          | Builds Docker image, taints master, applies ScaledJob    |
| `stop.py`                    | Cleans all jobs, taints, and shuts down services         |
| `mqtt_posture_analyzer_with_db.py` | Receives images via MQTT and analyzes posture      |
| `gpu_affinity_watcher.py`    | Picks lowest GPU node and patches job nodeAffinity       |
| `patch_scaledjob.py`         | Modifies `posture-job.yaml` with selected nodeAffinity   |
| `cpu_monitor_and_offload.py` | gRPC KEDA scaler using GPU metrics from Prometheus       |
| `posture-job.yaml`           | KEDA ScaledJob template                                 |
| `Dockerfile`                 | Builds the posture analyzer container                    |
| `externalscaler.proto`       | gRPC definition for KEDA external scaler                 |

---

## 🧠 How It Works

1. MQTT devices send base64-encoded JPEGs to topics like `images/pi1`
2. `build_and_push.py` builds the Docker image and starts the watchers
3. KEDA + Prometheus + custom scaler decide if a posture analysis job should run
4. A job is dynamically launched on the least busy GPU node
5. The container analyzes the image and stores:
   - Annotated image (optional)
   - Analysis data in PostgreSQL

---

## 🧪 Running the System

### ✅ Build and Launch
```bash
python3 build_and_push.py
```

This will:
- Stop any old containers and images
- Build and push `shahroz90/posture-analyzer` to Docker Hub
- Patch `posture-job.yaml` with best nodeAffinity
- Deploy the ScaledJob
- Start:
  - GPU watcher
  - CPU monitor
  - gRPC server for KEDA

### ⛔ Stop Everything
```bash
python3 stop.py
```

This will:
- Kill monitoring processes
- Delete posture-analyzer Jobs and Pods
- Untaint the master node
- Delete the patched YAML

---

## 🗃️ PostgreSQL Table Schema

```sql
CREATE TABLE posture_log (
  id SERIAL PRIMARY KEY,
  pi_id TEXT,
  filename TEXT,
  received_time TIMESTAMP,
  analyzed_time TIMESTAMP,
  neck_angle INTEGER,
  body_angle INTEGER,
  posture_status TEXT,
  landmarks_detected BOOLEAN,
  processed_by TEXT
);
```

---

## ✅ Example MQTT Workflow

1. Raspberry Pi publishes image to `images/pi1`
2. A job is launched on the best GPU node
3. The image is analyzed and logged to DB
4. System scales down automatically when idle

---

## 📄 License

MIT

---

## 👨‍💻 Maintainer

Developed by Shahroz Abbas. For support or testing inquiries, please reach out via GitHub or email.
