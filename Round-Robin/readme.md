# Round‑Robin K3s Scheduler with Posture Jobs — README



---

## Summary (What this is)

This project runs **10 independent posture‑analysis Jobs** (Dockerized Python apps) on a **K3s/Kubernetes** cluster and schedules their Pods using a **lightweight, custom *****round‑robin***** scheduler** — no Prometheus or CPU metrics required.

It includes a small scheduler (`rr-scheduler.py`) that:

- Watches for **Pending Pods** that request `schedulerName: rr-scheduler`.
- **Binds** each Pending Pod to the **next node in order** (round‑robin) using the Kubernetes **Binding API**.
- Skips nodes that aren’t **Ready** and advances to the next available node.
- Spreads Pods **evenly** across the cluster over time.

The project can build multi‑arch images, apply RBAC/manifests, create the Jobs, and start the scheduler with a **single command** (`python3 build.py`).

---

## Table of Contents

- [Architecture](#architecture)
- [Repo Layout](#repo-layout)
- [Prerequisites](#prerequisites)
- [Quick Start (TL;DR)](#quick-start-tldr)
- [Detailed Setup](#detailed-setup)
- [Configuration](#configuration)
- [How the Round‑Robin Scheduler Works](#how-the-round-robin-scheduler-works)
- [Run as a Cluster Deployment (optional)](#run-as-a-cluster-deployment-optional)
- [Local Demo (no Kubernetes)](#local-demo-no-kubernetes)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [License](#license)

---

## Architecture

- **K3s / Kubernetes** cluster with several worker nodes (e.g., `agx-desktop`, `orin-desktop`, `nano1-desktop`, etc.).
- **Jobs:** `posture-pi1`, `posture-pi1-1`, …, `posture-pi1-9`, each producing **1 Pod** that runs a Python posture analyzer (`Images_From_Pi1.py`, `Images_From_Pi1_1.py`, …).
- **Custom scheduler:** `rr-scheduler.py` with `schedulerName: rr-scheduler` to **bind** Pending Pods to nodes in a simple **round‑robin** order.
- **Result artifacts:** each analyzer saves **annotated images** and writes a **CSV summary** (per Job).

> Human‑friendly description: images come in via MQTT, the app checks posture with MediaPipe Pose, labels the image Good/Bad, and saves a CSV. The scheduler just makes sure pods are spread evenly, one after another, across the nodes.

---

## Repo Layout

```
.
├── build.py                     # One‑shot build/deploy/run helper (images + k8s apply)
├── rr-scheduler.py              # Custom round‑robin scheduler (uses Binding API)
├── rr-scheduler.yaml            # Scheduler Deployment/RBAC (applied by build.py)
├── posture-jobs.yaml            # 10 Jobs (one Pod each) using schedulerName: rr-scheduler
├── Dockerfile                   # Base Dockerfile for posture analyzers
├── Dockerfile.rr                # Dockerfile for the rr‑scheduler container
├── requirements.txt             # Python deps for analyzers (and local tools)
├── docker-compose.yml           # Optional local stack (MQTT, etc.)
├── stop.py                      # Collect results & clean up k8s jobs/resources
├── Images_From_Pi1.py           # Analyzer app (also _1.py … _9.py variants)
└── (other helper scripts)
```

> Note: We build **10 images** from the same Dockerfile by swapping the `APP` build‑arg to select `Images_From_Pi1_*.py`.

---

## Prerequisites

- A running **K3s/Kubernetes** cluster (you have `kubectl` access).
- **Docker with Buildx** (for multi‑arch builds).
- **Python 3.10+** on your operator machine (to run `build.py`).
- A container **registry** you can push to (Docker Hub, GHCR, etc.).

*(Prometheus is ****not**** required; scheduling is round‑robin.)*

---

## Quick Start (TL;DR)

1. **Clone** the repo and enter it.

2. *(Optional)* Create a virtual env and install Python deps:

   ```bash
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Check cluster access**:

   ```bash
   kubectl get nodes
   ```

4. **Build & launch everything**:

   ```bash
   python3 build.py
   ```

   What this does:

   - Builds & pushes **10 posture analyzer images** (multi‑arch)
   - Builds & pushes the **rr‑scheduler** image (`Dockerfile.rr`)
   - Applies **RBAC/Deployment** for the scheduler (`rr-scheduler.yaml`)
   - Applies **Jobs** (`posture-jobs.yaml`)

5. **Watch pods schedule and start**:

   ```bash
   kubectl get pods -l app=posture -o wide
   ```

---

## Detailed Setup

### 1) Install requirements (local)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2) Configure your image registry (optional)

In `build.py`, images default to tags like:

```
shahroz90/posture-analyzer-pi1:latest
shahroz90/posture-analyzer-pi1-1:latest
...
shahroz90/posture-analyzer-pi1-9:latest
```

Change these to your own registry if needed.

### 3) Apply the scheduler & RBAC

`build.py` already does this, but manually you can run:

```bash
kubectl apply -f rr-scheduler.yaml
```

This creates the scheduler Deployment/ServiceAccount/ClusterRoleBinding.

### 4) Deploy the Jobs

`build.py` also does this; manual command:

```bash
kubectl apply -f posture-jobs.yaml
```

Ensure each Job template includes:

```yaml
spec:
  template:
    spec:
      schedulerName: rr-scheduler
```

### 5) Verify scheduling

```bash
kubectl get pods -l app=posture -o wide
```

You should see Pods bound across nodes in a roughly even, round‑robin order.

---

## Configuration

The scheduler reads these env vars (sane defaults provided):

| Variable         | Default        | Description                                                                                                                                                  |
| ---------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SCHEDULER_NAME` | `rr-scheduler` | Must match `spec.schedulerName` in `posture-jobs.yaml`.                                                                                                      |
| `RR_NODE_ORDER`  | *(auto)*       | Comma‑separated node names (e.g., `agx-desktop,orin-desktop,nano1-desktop`). If unset, the scheduler uses the cluster’s current Ready nodes in stable order. |
| `POD_NAMESPACE`  | `default`      | Namespace where posture Jobs run.                                                                                                                            |
| `LABEL_SELECTOR` | `app=posture`  | Label selector to find Pods to schedule.                                                                                                                     |

To override when running locally:

```bash
export RR_NODE_ORDER="agx-desktop,orin-desktop,nano1-desktop"
python3 rr-scheduler.py
```

---

## How the Round‑Robin Scheduler Works

**Initial placement**

1. List **Ready** nodes (or use `RR_NODE_ORDER`).
2. Find **Pending** pods with `schedulerName: rr-scheduler` and matching labels.
3. **Bind** each Pending pod to the **next node** in the list (round‑robin), advancing an internal index.

**On conflicts**

- If a pod is already bound (HTTP 409), the scheduler **skips** it gracefully.
- If a node becomes NotReady, it’s **skipped** until Ready again.

**Lifecycle**

- The scheduler loops, picking up new Pending pods and continuing the round‑robin cycle so distribution stays even as Jobs complete or restart.

> Why Binding API? It schedules existing Pending pods **without** deleting them, keeping Job ownership intact and avoiding “pod storms”.

---

## Run as a Cluster Deployment (optional)

You can run the scheduler inside the cluster (instead of your terminal) using `rr-scheduler.yaml`. Typical snippet:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rr-scheduler
  namespace: kube-system
spec:
  replicas: 1
  selector:
    matchLabels: { app: rr-scheduler }
  template:
    metadata:
      labels: { app: rr-scheduler }
    spec:
      serviceAccountName: rr-scheduler
      containers:
      - name: scheduler
        image: YOUR_REGISTRY/rr-scheduler:latest
        command: ["python3", "/app/rr-scheduler.py"]
        env:
        - name: SCHEDULER_NAME
          value: "rr-scheduler"
        - name: LABEL_SELECTOR
          value: "app=posture"
        - name: RR_NODE_ORDER
          value: "agx-desktop,orin-desktop,nano1-desktop"
```

Apply it with:

```bash
kubectl apply -f rr-scheduler.yaml
```

---

## Local Demo (no Kubernetes)

You can run **one** analyzer locally to see posture analysis end‑to‑end.

1. Create a virtual env & install deps

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Start an MQTT broker (easiest via Docker):

```bash
docker run -it --name mqtt -p 1883:1883 eclipse-mosquitto
```

3. Set basic env vars

```bash
export MQTT_BROKER=localhost
export MQTT_PORT=1883
export MQTT_TOPIC=images/input
# Optional DB (leave off to disable):
# export DB_ENABLED=true
# export DB_HOST=localhost
# export DB_PORT=5432
# export DB_NAME=posture
# export DB_USER=postgres
# export DB_PASSWORD=secret
```

4. Run an analyzer

```bash
python Images_From_Pi1.py
```

5. Publish a test image (Python snippet)

```python
import base64, paho.mqtt.client as mqtt
c = mqtt.Client(); c.connect("localhost",1883,60)
with open("sample.jpg","rb") as f: payload = base64.b64encode(f.read())
c.publish("images/input", payload); c.disconnect()
print("Sent image to MQTT topic: images/input")
```

You’ll see an **annotated image** plus a **CSV summary** in the working directory.

---

## Troubleshooting

**Pods stay Pending**

- Ensure `schedulerName: rr-scheduler` is in the Job template.
- Make sure the scheduler is **running** (locally or as a Deployment).
- Check RBAC/Deployment were applied: `kubectl get deploy -n kube-system rr-scheduler`.
- Inspect pod events: `kubectl describe pod <name> | sed -n '/Events:/,$p'`.

**Binding errors / 409**

- `409` means the pod was already bound (race) — harmless, the scheduler skips it.

**Results not collected**

- Run `python stop.py` to copy CSVs from pods into `./results/` and clean up jobs.

**MediaPipe/OpenCV install woes (local)**

- Use Python **3.10+** and reinstall: `pip install --no-cache-dir mediapipe opencv-python`.

---

## FAQ



**Q: Can I change the number of Jobs/Pods?** A: Yes. Edit `posture-jobs.yaml` (add/remove Jobs). You can also consolidate into one Job and adjust `parallelism` if desired.

**Q: Where do results go?** A: Each analyzer writes annotated images and a CSV (e.g., `pi1_results.csv`, `pi1_5_results.csv`). `stop.py` collects them from pods.

---

##

---

### One‑Minute Recap

- `python3 build.py` builds images, deploys `rr-scheduler`, and creates Jobs.
- Pods get placed **round‑robin** across nodes.
- Each Job analyzes posture on incoming images and writes a **CSV** + **annotated images**.
- `python3 stop.py` collects results and cleans up.
