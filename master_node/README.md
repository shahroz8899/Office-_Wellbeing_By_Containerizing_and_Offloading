Always run inside a virtual environment.

# 🧠 Posture Analyzer: Edge Offloading System

This project implements a real-time posture analysis system using containerized image processing, MQTT messaging, and Kubernetes-based offloading. It dynamically runs image processing either locally (on the master node) or remotely (on a worker node), based on CPU load.

## 📦 Components

- **MQTT Publisher (Raspberry Pi):** Publishes base64-encoded images from cameras.
- **Master Node (Jetson Orin/Nano/NUC):**
  - Receives images via MQTT.
  - Analyzes posture locally if CPU < 60%.
  - Offloads analysis to a worker node if CPU ≥ 60%.
- **Worker Node (e.g., AGX Xavier):** Runs the same Docker container to process images.
- **Supabase Database:** Stores metadata (e.g., timestamps, angles, posture status, node info).
- **Docker + Docker Hub:** Used to containerize and distribute the posture analyzer.
- **K3s + Kubernetes Job:** Orchestrates execution across nodes.

## 🚀 Features

- 🔁 **CPU-Based Load Balancing:** Automatically offloads to worker if master is overloaded.
- 📸 **Real-Time Posture Detection:** Uses MediaPipe for landmark detection.
- 🧠 **Metadata Logging:** Logs analysis data to Supabase (PostgreSQL).
- 🐳 **Multi-Architecture Docker Support:** Builds for `arm64` and `amd64`.
- 🔁 **Kubernetes Offloading:** Worker pulls image from Docker Hub and runs job.
- 📁 **Organized Folder Structure:** Images saved under folders like `analyzed_images_from_pi1/`.

## 🛠️ Setup

### 1. Clone Repository
```bash
git clone https://github.com/yourusername/posture-analyzer.git
cd posture-analyzer
```
### How to run the project
### 2. Build and Push Docker Image
```bash
python3 build_and_push.py
```



### 4. Manually Run on Worker (for testing)
```bash
docker run --rm -it \
  -e SUPABASE_HOST=aws-0-eu-north-1.pooler.supabase.com \
  -e SUPABASE_DB=postgres \
  -e SUPABASE_USER=postgres.yvqqpgixkwsiychmwvkc \
  -e SUPABASE_PASSWORD=University12@ \
  -e SUPABASE_PORT=5432 \
  -e SUPABASE_SSL=require \
  -v ~/analyzed_images:/app/analyzed_images \
  shahroz90/posture-analyzer
```

## 📂 Folder Structure

```
Project2.0/
├── analyzed_images/
├── Dockerfile
├── requirements.txt
├── mqtt_posture_analyzer_with_db.py
├── cpu_monitor_and_offload.py
├── build_and_push.py
├── docker-compose.yml
├── posture-job.yaml
```

## 🧠 Data Logged to Supabase

| Field              | Description                           |
|-------------------|---------------------------------------|
| `pi_id`           | Source Pi (e.g., pi1, pi2)             |
| `filename`        | Image filename                        |
| `received_time`   | When image was received               |
| `analyzed_time`   | When analysis completed               |
| `neck_angle`      | Detected neck angle                   |
| `body_angle`      | Detected torso angle                  |
| `posture_status`  | "Good", "Bad", etc.                   |
| `landmarks_detected` | True/False                        |
| `processed_by`    | Hostname of node that processed it    |

## 📸 Sample Result

Annotated images saved under:

```
/home/agx/analyzed_images/analyzed_images_from_pi1/
```

---

## 🧑‍💻 Author

**Shahroz Abbas**  
Doctoral Researcher, University of Oulu  
[Email](mailto:shahroz.abbas@oulu.fi)

---


