# 🧠 Posture Analysis Job Offloading System (GPU-Based with Prometheus)

This project receives posture images from Raspberry Pis and offloads posture analysis jobs to the most underloaded GPU-equipped worker node in a Kubernetes cluster. The system relies on Prometheus to monitor GPU usage and dynamically patches and deploys Kubernetes jobs to the optimal node.

---

## 📦 Project Features

- 📸 Posture image input via MQTT
- 📊 GPU load-based job scheduling using Prometheus
- 🐳 Dockerized posture analyzer with Supabase DB logging
- ☁️ Jobs offloaded via Kubernetes and node affinity
- 🚫 Master node tainted to avoid overload
- 🧽 Automatic job cleanup after completion

---

## 📁 Folder Structure

```
Master Tainted + GPU Based Scheduling/
├── build_and_push.py           # Builds and pushes Docker image, taints master node
├── stop.py                    # Stops system and untaints master
├── cpu_monitor_and_offload.py # Prometheus-based job scheduler
├── mqtt_posture_analyzer_with_db.py # Image processing entrypoint
├── gpu_scaler.py              # Manual Prometheus GPU stats tester
├── Dockerfile                 # Posture analyzer image definition
├── docker-compose.yml         # Local run support
├── requirements.txt           # Python dependencies
├── posture-job.yaml           # Template for K8s job (patched dynamically)
├── patched-job.yaml           # Final job applied to cluster
```

---

## 🚀 How to Run the Project

### ✅ Prerequisites

- Kubernetes cluster with labeled worker nodes (`role=worker`)
- Prometheus scraping GPU usage metrics (`jetson_gpu_usage_percent`, etc.)
- Docker + Docker Hub credentials
- Supabase PostgreSQL setup
- Python 3.8+ environment

### 🔨 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 🧱 2. Build and Launch the System

```bash
python3 build_and_push.py
```

This will:
- Stop previous containers/images
- Build & push Docker image (`shahroz90/posture-analyzer`)
- Taint master node
- Start monitoring + auto-offloading jobs

### 🧹 3. Stop the System

```bash
python3 stop.py
```

This will:
- Kill offloading monitor
- Delete Kubernetes jobs
- Bring down containers
- Untaint the master node

---

## ⚙️ How Offloading Works

- GPU usage is queried from Prometheus (localhost:9090)
- If any worker node has GPU usage < 60%, it is selected
- `posture-job.yaml` is patched with:
  ```yaml
  nodeName: <selected-node>
  ```
- Job is launched via:
  ```bash
  kubectl apply -f patched-job.yaml
  ```

Each job runs:
- `mqtt_posture_analyzer_with_db.py` inside the container
- Subscribes to MQTT broker, processes images, logs results to Supabase

---

## 📂 Key Scripts

### `build_and_push.py`
- Builds & pushes image
- Taints master node
- Starts monitor and listener

### `stop.py`
- Deletes jobs and containers
- Kills `cpu_monitor_and_offload.py`
- Untaints master node

### `cpu_monitor_and_offload.py`
- Prometheus-based scheduler
- Patches and deploys job to best node

### `gpu_scaler.py`
- For testing Prometheus GPU queries manually

---

## 🔌 MQTT + Supabase

The analyzer script:
- Subscribes to topics like `images/pi1`, `images/pi2`
- Runs posture detection using MediaPipe
- Logs:
  - pi_id, filename, angles, posture status, timestamps
- Saves to: Supabase PostgreSQL

---

## 🛠 Prometheus Metrics Used

- `jetson_gpu_usage_percent` (for Jetson AGX nodes)
- `jetson_orin_gpu_load_percent` (for Jetson Orin nodes)

---

## 📝 Notes

- `ttlSecondsAfterFinished: 60` in job spec cleans up jobs automatically
- Taint on master ensures workloads go to GPU workers
- You must rebuild and push image after changing `mqtt_posture_analyzer_with_db.py`

---

## 📊 Future Improvements

- 🔄 Integrate KEDA external scaler (gRPC Prometheus scaler)
- 📈 Add Grafana dashboards
- 🧠 Real-time DB feedback loop for posture analytics
- 🧠 Combine with memory/CPU-based scalers

---

## 👤 Author

**Muhammad Shahroz Abbas**  
📧 [shahroz.abbas@oulu.fi](mailto:shahroz.abbas@oulu.fi)  


---

✅ Ready for testing and deployment.
