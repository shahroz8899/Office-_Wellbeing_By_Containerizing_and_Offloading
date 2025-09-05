# Posture Analyzer at the Edge — **Updated Scheduling** (KEDA + gRPC + Prometheus)

This repository turns a small Kubernetes cluster of Jetson/edge nodes into a **GPU‑aware, self‑balancing posture analysis farm**.  
It ingests images from multiple Raspberry Pis (via MQTT), analyzes human posture with MediaPipe + OpenCV, stores annotated results, and **auto‑schedules Kubernetes Jobs** to the **least‑busy GPU nodes** using **KEDA** with a **custom gRPC External Scaler** that reads **Prometheus** metrics.

> **What’s new (updated scheduling):**
>
> - **Initial placement = even spread** across all available GPU nodes. If the number of ScaledJobs doesn’t divide evenly, the **extra** job(s) go to the node(s) with the **lowest GPU usage**, tie‑broken **randomly**.
> - A new **gpu_balancer.py** performs a **30‑second observation window**, computes **per‑node average GPU usage**, and **offloads at most one job per overloaded node per loop** to the lowest‑usage **under‑threshold** node (random tie on equals). This repeats until all nodes are **stable** (≤ threshold).
> - The External Scaler (`cpu_monitor_and_offload.py`) is **debounced** so KEDA polling doesn’t thrash jobs while the balancer is stabilizing.

---

## ✨ Features

- **Distributed posture detection** with MediaPipe Pose + OpenCV.
- **Per‑Pi ScaledJobs** (one KEDA ScaledJob per Pi/topic) for isolation and control.
- **GPU‑aware scheduling** driven by Prometheus GPU usage metrics.
- **Even initial spread** + **gentle rebalancing** based on 30s averages.
- **Batteries‑included** scripts to build/push images, patch/apply manifests, run/stop safely.

---

## 🗺️ Architecture

```
Raspberry Pi(s)
   │ (MQTT)
   ▼
Analyzer Pods (Images_From_Pi*.py)  →  Annotated frames + posture metrics  →  Database (e.g., Supabase)

Prometheus  ← node exporters on Jetsons (GPU usage % per node)

KEDA (ScaledJobs)  ⇄  gRPC  ⇄  External Scaler (cpu_monitor_and_offload.py)
                               │
                               └─ launches →  gpu_balancer.py  (observe 30s → offload 1 per overloaded node per loop)

Initial placement helper: patch_scaledjob.py  → injects nodeAffinity for **even spread** (extras → lowest usage; tie random)
```

---

## ⚖️ Scheduling Lifecycle (updated logic)

### 1) **Initial placement (first‑time scheduling)**

When you apply the ScaledJobs:
1. `patch_scaledjob.py` queries Prometheus to get a **current snapshot** of GPU usage per node.
2. It plans an **even distribution** of ScaledJobs across all available nodes:
   - Each node gets either ⌊N/M⌋ or ⌈N/M⌉ jobs, where N = number of ScaledJobs and M = number of nodes with valid metrics.
   - Any **extra** jobs are assigned to the node(s) with the **lowest** measured usage; if multiple nodes tie at that minimum, the script **chooses randomly** among those nodes to prevent dog‑piling.
3. It writes `patched-job-*.yaml` with an injected:
   ```yaml
   affinity:
     nodeAffinity:
       requiredDuringSchedulingIgnoredDuringExecution:
         nodeSelectorTerms:
         - matchExpressions:
           - key: gpu-node
             operator: In
             values: [<chosen-node>]
   ```
4. Applying `patched-job-*.yaml` ensures the **first** Job per ScaledJob lands on its assigned node.

### 2) **Runtime balancing (observe → gently offload → repeat)**

Once KEDA reports **Active=True** and pods are running, `gpu_balancer.py` enters a loop:

1. **Observe 30s window**: sample GPU usage every few seconds (default 5s) and compute a **per‑node average** over **30 seconds**.
2. **Check threshold** (default **50%**, configurable):
   - If **all nodes ≤ threshold** → **stable**, do nothing, sleep 30s, and observe again.
   - If **one or more nodes > threshold** → each such node is **overloaded**.
3. **Offload** (one per overloaded node per loop):
   - For **each overloaded node**, select **one running posture job/pod** on that node.
   - **Pick a destination node** from those **≤ threshold** with the **lowest average usage** (random tie‑break).
   - **Delete the Job(s)** for that ScaledJob (controller cleans up), **delete leftover pods** if any, **patch that ScaledJob’s `nodeAffinity`** to the destination node.
4. **Repeat**: sleep 30s, recompute per‑node averages, and repeat until **no node exceeds the threshold**.

This **“one‑offload‑per‑overloaded‑node per loop”** rule avoids thrashing and slowly converges the system to a balanced state.

### 3) **KEDA integration (debounced)**

- **KEDA ↔ External Scaler**:  
  - `IsActive` returns **True** if **any** node has usage **below** the threshold; otherwise **False**.  
  - `GetMetricSpec` advertises `gpu_trigger` with `targetSize: 1`.  
  - `GetMetrics` returns a synthetic capacity (`sum(max(0, 100 - usage))`).

- **Debounce during stabilization**:  
  The scaler keeps returning **Active=True** for a short **stabilize window** after it detects capacity, so KEDA doesn’t tear down jobs while `gpu_balancer.py` is still rebalancing. This prevents the “delete every 30s” flapping you may see in naïve setups.

---

## 🧩 Repository Layout (updated)

### Orchestration & Control

- **`build_and_push.py`**  
  - Builds & pushes **multi‑arch** analyzer images (`--platform linux/amd64,linux/arm64`).  
  - Taints the master (e.g., `nuc`) to repel posture jobs.  
  - Runs **`patch_scaledjob.py`** (even initial spread) → writes `patched-job-*.yaml`.  
  - Applies all `patched-job-*.yaml`.  
  - Starts the **External Scaler** (gRPC on `:50051`) and an ENTER‑to‑stop helper.

- **`stop.py`**  
  - On ENTER: `docker-compose down`, kills scaler/balancer helpers, **deletes Jobs first** then leftover Pods, optionally deletes ScaledJobs, and **untaints** the master. (Updated to use robust matching and prefixes.)

### Scheduling & Scaling Brains

- **`cpu_monitor_and_offload.py`** — **External Scaler (gRPC server for KEDA)**  
  - `IsActive` (debounced), `GetMetricSpec`, `GetMetrics`.  
  - Reads GPU usage via Prometheus.  
  - Ensures `gpu_balancer.py` is running on Active.  
  - On sustained global overload may return inactive (no frantic deletions during stabilization).

- **`gpu_balancer.py`** — **30‑second average balancer** *(new)*  
  - Observes **30s**, computes per‑node averages, compares against the threshold.  
  - For each **overloaded** node, **offloads at most one** job/pod to the **lowest‑usage under‑threshold** node (random tie‑break), by patching that ScaledJob’s `nodeAffinity` and recreating its Job.  
  - Repeats until the cluster is **stable**.

- **`patch_scaledjob.py`** — **Even initial spread** *(updated)*  
  - Reads **instantaneous** GPU usage per node.  
  - Distributes all ScaledJobs **evenly**; places any remainder on the **lowest‑usage** nodes; random tie‑break.  
  - Injects `nodeAffinity` into base YAMLs → `patched-job-*.yaml`.

### Kubernetes Manifests (KEDA)

- **`posture-job-*.yaml`** — Base ScaledJob templates (pre‑patch).  
  - `triggers[0].type: external` with `metadata.scalerAddress: <HOST|IP>:50051`.  
  - One ScaledJob per Pi stream (`pi1`, `pi1-1`, `pi2-3`, `pi3`, …).  
  - Container runs the matching `Images_From_Pi*.py`.  
  - DB env injected via env vars (migrate to Secrets for production).

- **`patched-job-*.yaml`** — Rendered ScaledJobs with **nodeAffinity** set per the even‑spread plan.

### Analyzer Apps

- **`Images_From_Pi*.py`** — per‑stream analyzers:  
  - Subscribe to MQTT topic, decode image, run MediaPipe Pose.  
  - Compute **neck/body angles**, label posture **Good/Bad**, overlay graphics.  
  - Save annotated frames and write telemetry/metrics to the DB.

### gRPC / Misc

- **`externalscaler.proto`**, **`externalscaler_pb2.py`**, **`externalscaler_pb2_grpc.py`** — KEDA External Scaler API & generated stubs.  
- **`docker-compose.yml`** — optional local run (no K8s), mounting `./analyzed_images`.  
- **`Dockerfile`** — uses `--build-arg APP=<script.py>` to bake each analyzer variant.  
- **`last_node.txt`** — small state file used by the balancer/watcher to remember the last “best” node and avoid flapping.

---

## ⚙️ Configuration

### Prometheus Metrics Map
All 3 scripts use a `GPU_QUERIES` map. Update IPs/metric names to your exporters:
```python
GPU_QUERIES = {
  "agx-desktop": {"instance": "192.168.1.135:9100", "metric": "jetson_gpu_usage_percent"},
  "orin-desktop": {"instance": "192.168.1.118:9100", "metric": "jetson_orin_gpu_load_percent"},
  # ...
}
```

### Balancer / Scaler Knobs
- **`GPU_THRESHOLD`** (default `50`): node considered **overloaded** if avg usage > threshold.  
- **Window**: `gpu_balancer.py` uses **30s** (sample every 5s by default).  
- **Max offload rate**: **1 job per overloaded node per loop**.  
- **Debounce** (scaler): small stabilization window so KEDA keeps `Active=True` while balancing.

> Tip: You can make `GPU_THRESHOLD` an environment variable consumed by both `gpu_balancer.py` and `cpu_monitor_and_offload.py` for cluster‑wide tuning.

### Node Labels
Nodes must be labeled with `gpu-node=<nodeName>`. The manifests/patcher depend on this for `nodeAffinity`.

### External Scaler Address
Each ScaledJob has:
```yaml
triggers:
- type: external
  metadata:
    scalerAddress: <HOST_OR_IP>:50051
```
Ensure the scaler is reachable from the cluster (you can run it on a node or expose it via a Service).

---

## ▶️ Run (Kubernetes)

1) **Build, patch, apply, start scaler**
   ```bash
   python3 build_and_push.py
   ```
   - Builds/pushes images for all analyzer variants.
   - Patches base YAMLs for **even initial spread**.
   - Applies `patched-job-*.yaml`.
   - Starts the External Scaler (gRPC on `:50051`) + ENTER‑to‑stop helper.

2) **Check status**
   ```bash
   kubectl get scaledjobs
   kubectl get jobs
   kubectl get pods -o wide
   ```

3) **Stop**
   Press **ENTER** in the `build_and_push.py` terminal. The helper will kill processes and **delete Jobs first** (then Pods), and untaint the master node.

---

## ▶️ Run Locally (Compose)

```bash
docker-compose up -d
# test image processing pipeline & DB writes
docker-compose down
```
Outputs are stored in `./analyzed_images`.

---

## 🧪 Posture Logic (Analyzer)

- MediaPipe Pose → key landmarks.  
- **Angles**: neck (ear–shoulder vs vertical), body (hip–shoulder vs vertical).  
- **Label**: “Good”/“Bad” via thresholds.  
- **Artifacts**: overlayed frames + DB rows (angles, status, timestamps, Pi ID, host).

---

## 🔐 Security

- Move DB credentials from plain‑text YAML/compose into **Kubernetes Secrets** or `.env` files not committed to VCS.  
- Restrict access to the scaler port (`:50051`) to cluster nodes only (e.g., ClusterIP Service + NetworkPolicy).

---

## 🛠️ Troubleshooting

- **Pods churn at `pollingInterval` cadence** → ensure the External Scaler’s debounce is active and that `gpu_balancer.py` is running; check Prometheus metric availability.  
- **No movements** → ensure node labels match, Prometheus is reachable, and the service account has rights to `kubectl patch` and `kubectl delete job/pod`.  
- **All nodes overloaded** → balancer won’t offload; add capacity or reduce number of ScaledJobs.

---

## 📄 License

MIT (or your preferred license).

---

## 🙌 Acknowledgements

Built with [KEDA](https://keda.sh/) External Scaler gRPC pattern, Prometheus, and MediaPipe.
