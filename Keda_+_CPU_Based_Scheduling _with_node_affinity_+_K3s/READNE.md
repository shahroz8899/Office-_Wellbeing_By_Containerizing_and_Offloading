# CPU-Aware K3s Scheduler with Node Affinity (Posture Jobs)

This project runs 10 independent **posture analysis Jobs** (Dockerized Python apps) on a **K3s/Kubernetes** cluster and schedules their Pods based on **live CPU usage** from Prometheus.

It includes a lightweight **custom scheduler** (`cpu_scheduler.py`) that:
- Scrapes node CPU every 10s via Prometheus.
- Schedules pending Pods to **underloaded** nodes (< **90%** CPU).
- Spreads Pods **evenly** across available nodes.
- Every **30s**, offloads (deletes) Pods from **overloaded** nodes (≥ 90%) so the Job controller recreates them; the scheduler then places them on the least-loaded nodes.

The project can build multi-arch images, apply RBAC, create the Jobs, and start the scheduler with a single command (`python3 build.py`).

---

## Table of Contents

1. [Architecture](#architecture)
2. [Repo Layout](#repo-layout)
3. [Prerequisites](#prerequisites)
4. [Quick Start (TL;DR)](#quick-start-tldr)
5. [Detailed Setup](#detailed-setup)
6. [Configuration](#configuration)
7. [How the Scheduler Works](#how-the-scheduler-works)
8. [Run as a Cluster Deployment (optional)](#run-as-a-cluster-deployment-optional)
9. [Troubleshooting](#troubleshooting)
10. [FAQ](#faq)
11. [License](#license)

---

## Architecture

- **K3s / Kubernetes** cluster with several worker nodes (e.g., `agx-desktop`, `orin-desktop`, `nano1-desktop`, `nano2-desktop`, `orin1-desktop`, `orin2-desktop`).
- **Prometheus** scraping **node exporter** on each node (we use 10s CPU average).
- **Jobs**: `posture-pi1`, `posture-pi1-1`, …, `posture-pi1-9`, each producing 1 Pod (Python apps like `Images_From_Pi1.py`, `Images_From_Pi1_1.py`, …).
- **Custom scheduler** (`cpu_scheduler.py`) with `schedulerName: cpu-scheduler` to:
  - Bind **Pending** Pods to chosen nodes (Kubernetes **Binding** API).
  - Offload Pods from overloaded nodes so they get rescheduled.

---

## Repo Layout

```
.
├── build.py                        # One-shot build/deploy/run helper
├── cpu_scheduler.py                # Custom CPU-aware scheduler (Binding API)
├── cpu_metrics.py                  # Prometheus queries & node mapping helpers
├── posture-jobs.yaml               # 10 Jobs (one Pod each) using schedulerName: cpu-scheduler
├── cpu-scheduler-rbac.yaml         # RBAC for scheduler (SA + ClusterRole + Binding)
├── Dockerfile                      # Single Dockerfile used for posture analyzers
├── requirements.txt                # Python deps for posture apps + scheduler
├── Images_From_Pi1.py              # Analyzer app (and Images_From_Pi1_1.py ... _9.py)
├── docker-compose.yml              # optional local use (not required for k8s)
└── (other helper scripts)
```

> **Note**: We build 10 images from the same Dockerfile by swapping the `APP` build-arg.

---

## Prerequisites

- A running **K3s** or **Kubernetes** cluster (you have `kubectl` access).
- **Prometheus** scraping Node Exporter on each node (standard setup).
- Docker with **Buildx** (for multi-arch builds).
- Python 3.10+ on your operator machine (to run `build.py`).
- A container registry you can push to (Docker Hub, GHCR, etc.) — update image names if you use a different registry.

---

## Quick Start (TL;DR)

1. Clone the repo and enter it.
2. (Optional) Create a virtual env and install Python deps:
   ```bash
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Make sure `kubectl` points to the right cluster:
   ```bash
   kubectl get nodes
   ```
4. Run the all-in-one builder/launcher:
   ```bash
   python3 build.py
   ```
   What this does:
   - Builds and pushes 10 posture analyzer images (multi-arch).
   - Applies scheduler **RBAC** (`cpu-scheduler-rbac.yaml`).
   - Applies **Jobs** (`posture-jobs.yaml`).
   - Starts the **custom scheduler** (`python3 cpu_scheduler.py`) which binds Pending Pods.

5. Watch Pods schedule and start:
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
In `build.py`, images default to Docker Hub tags like:
```
shahroz90/posture-analyzer-images_from_pi1:latest
...
shahroz90/posture-analyzer-images_from_pi1_9:latest
```
Change these to your own registry/repo if needed.

### 3) Apply RBAC for the custom scheduler
`build.py` already does this, but you can do it manually:
```bash
kubectl apply -f cpu-scheduler-rbac.yaml
```

### 4) Deploy the Jobs
`build.py` also does this; manual command:
```bash
kubectl apply -f posture-jobs.yaml
```

### 5) Run the scheduler (from your laptop or server)
`build.py` runs it for you. To run manually:
```bash
python3 cpu_scheduler.py
```
- If you run **outside** the cluster, it uses your local `~/.kube/config`.
- If you run **inside** the cluster (as a Pod), it uses in-cluster auth.

---

## Configuration

The scheduler reads a few env vars (all have sane defaults):

| Variable                       | Default            | Description |
|-------------------------------|--------------------|-------------|
| `POD_NAMESPACE`               | `default`          | Namespace where Jobs run. |
| `POD_LABEL_SELECTOR`          | `app=posture`      | Label selector for posture pods. |
| `SCHEDULER_NAME`              | `cpu-scheduler`    | Must match `spec.schedulerName` in `posture-jobs.yaml`. |
| `SCHEDULING_INTERVAL_SECONDS` | `30`               | Loop period to re-check CPU & offload. |
| `CPU_THRESHOLD`               | `90`               | Overload threshold (% used). |
| `MIN_POD_AGE_SECONDS`         | `5`                | Avoid racing brand-new Pending pods. |

To change them when running locally:
```bash
export CPU_THRESHOLD=85
python3 cpu_scheduler.py
```

---

## How the Scheduler Works

### At First Run (Initial Scheduling)
1. Scrape Prometheus for **10-second average CPU** on all worker nodes.
2. Identify **underloaded** nodes (< 90% CPU by default).
3. Enumerate **Pending** posture Pods with `schedulerName: cpu-scheduler`.
4. Spread them **evenly** across underloaded nodes.
5. For each:
   - (Optional) **label** the pod with `cpu-scheduler/target-node=<node>`.
   - **Bind** the pod to the node using the **Pod Binding** API (no delete/recreate).

### Every 30 Seconds (Loop)
1. Re-scrape CPU usage.
2. If any node is **overloaded** (≥ 90%):
   - Find **Running** posture Pods on that node and **delete** them (fast).
   - The Job controller will create **new Pending** Pods.
3. **Schedule** any Pending Pods again to the **least-loaded** under-threshold nodes (balanced).

### Completion
- When no **Pending** and **Running** posture Pods remain, the scheduler **exits**.

> We **don’t** mutate `spec.affinity` on existing pods (immutable). We record our decision via a **label** and rely on **Binding** for placement.

---

## Run as a Cluster Deployment (optional)

Instead of running `cpu_scheduler.py` from your shell, you can deploy it as a single-replica controller:

```yaml
# cpu-scheduler-deploy.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cpu-scheduler
  namespace: kube-system
spec:
  replicas: 1
  selector:
    matchLabels: { app: cpu-scheduler }
  template:
    metadata:
      labels: { app: cpu-scheduler }
    spec:
      serviceAccountName: cpu-scheduler
      containers:
      - name: scheduler
        image: YOUR_REGISTRY/cpu-scheduler:latest
        imagePullPolicy: IfNotPresent
        command: ["python3", "/app/cpu_scheduler.py"]
        env:
        - name: POD_NAMESPACE
          value: "default"
        - name: SCHEDULER_NAME
          value: "cpu-scheduler"
        - name: CPU_THRESHOLD
          value: "90"
        - name: SCHEDULING_INTERVAL_SECONDS
          value: "30"
```

Build and push an image that contains `cpu_scheduler.py` and `cpu_metrics.py`, then:
```bash
kubectl apply -f cpu-scheduler-rbac.yaml
kubectl apply -f cpu-scheduler-deploy.yaml
```

---

## Troubleshooting

**Pods stay Pending**
- Ensure Jobs use `spec.template.spec.schedulerName: cpu-scheduler`.
- Make sure the scheduler is **running** (locally or as a Deployment).
- Check RBAC is applied (`cpu-scheduler-rbac.yaml`).
- Look at pod events:
  ```bash
  kubectl describe pod <name> | sed -n '/Events:/,$p'
  ```

**“Forbidden: pod updates may not change fields … Affinity”**
- Expected. Don’t patch `spec.affinity` after creation. This project **binds** pods and optionally **labels** them.

**Binding errors / status 409**
- 409 = already bound (race) → harmless. The scheduler logs “Bind skipped …”.

**Prometheus mapping seems off**
- Confirm that your `cpu_metrics.py` maps exporter IPs to node names correctly for your cluster (K3s Node Exporter pods often expose `podIP:9100` → map `podIP` → `spec.nodeName`).

**Large Docker build context**
- Add a `.dockerignore` to speed up builds:
  ```
  .git
  venv/
  __pycache__/
  *.pyc
  *.log
  *.csv
  analyzed_images/
  ```

---

## FAQ

**Q: Why not use the default Kubernetes scheduler?**  
A: We need **CPU-aware placement** and automatic **offloading** when nodes exceed a threshold. Our controller does a targeted strategy that the default scheduler doesn’t enforce out of the box.

**Q: Why Binding API instead of delete/recreate?**  
A: Binding directly schedules the **existing Pending pod**. It avoids “pod storms”, keeps Job ownership intact, and leads to clean Job completion semantics.

**Q: Can I change the number of Jobs/Pods?**  
A: Yes. Edit `posture-jobs.yaml` (add/remove Jobs) or change `parallelism/completions` if you convert to a single Job with multiple Pods.

---

