# gpu_balancer.py
#!/usr/bin/env python3
import json, os, random, re, subprocess, time
from urllib.parse import quote

# ---------- Config ----------
PROMETHEUS_URL = "http://localhost:9090"
QUERY_ENDPOINT = "/api/v1/query"
SAMPLE_INTERVAL_SEC = 5          # sample every 5s within the window
WINDOW_SEC = 30                  # 30s average per your policy
GPU_THRESHOLD = float(os.environ.get("GPU_THRESHOLD", "50"))  # configurable

# Nodes + metrics
GPU_QUERIES = {
    "agx-desktop": {"instance": "192.168.1.135:9100", "metric": "jetson_gpu_usage_percent"},
    "orin-desktop": {"instance": "192.168.1.118:9100", "metric": "jetson_orin_gpu_load_percent"},
    "orin1-desktop": {"instance": "192.168.1.77:9100", "metric": "jetson_orin1_gpu_usage_percent"},
    "orin2-desktop": {"instance": "192.168.1.35:9100", "metric": "jetson_orin2_gpu_usage_percent"},
    "orin3-desktop": {"instance": "192.168.1.XX:9100", "metric": "jetson_orin3_gpu_usage_percent"},
    "nano1-desktop": {"instance": "192.168.1.193:9100", "metric": "jetson_nano1_gpu_usage_percent"},
    "nano2-desktop": {"instance": "192.168.1.42:9100", "metric": "jetson_nano2_gpu_usage_percent"},
}

# ScaledJob name map for Pi IDs
PI_SCALEDJOBS = {
    "pi1": "posture-analyzer-scaledjob-pi1",
    "pi1-1": "posture-analyzer-scaledjob-pi1-1",
    "pi1-2": "posture-analyzer-scaledjob-pi1-2",
    "pi1-3": "posture-analyzer-scaledjob-pi1-3",
    "pi1-4": "posture-analyzer-scaledjob-pi1-4",
    "pi2": "posture-analyzer-scaledjob-pi2",
    "pi2-1": "posture-analyzer-scaledjob-pi2-1",
    "pi2-2": "posture-analyzer-scaledjob-pi2-2",
    "pi2-3": "posture-analyzer-scaledjob-pi2-3",
    "pi2-4": "posture-analyzer-scaledjob-pi2-4",
    "pi3": "posture-analyzer-scaledjob-pi3",
}
SCALEDJOB_NAME_PREFIX = "posture-analyzer-scaledjob-pi"  # for parsing running pods

# ---------- Helpers ----------
def run(cmd, check=True, capture=False):
    shell = isinstance(cmd, str)
    try:
        if capture:
            return subprocess.check_output(cmd, shell=shell, stderr=subprocess.STDOUT, text=True)
        subprocess.check_call(cmd, shell=shell)
        return ""
    except subprocess.CalledProcessError as e:
        if capture:
            print(e.output)
        if check:
            raise
        return ""

def query_once(metric, instance):
    url = f"{PROMETHEUS_URL}{QUERY_ENDPOINT}?query={quote(f'{metric}{{instance=\"{instance}\"}}')}"
    try:
        out = run(["curl", "-sS", url], capture=True)
        data = json.loads(out)
        if data.get("status") != "success":
            return None
        result = data.get("data", {}).get("result", [])
        if not result or not result[0].get("value"):
            return None
        return float(result[0]["value"][1])
    except Exception as e:
        print(f"❌ Prom query failed for {instance}: {e}")
        return None

def sample_avg_usages():
    """Sample every SAMPLE_INTERVAL_SEC for WINDOW_SEC, return average GPU usage per node."""
    samples_needed = max(1, WINDOW_SEC // SAMPLE_INTERVAL_SEC)
    acc = {n: [] for n in GPU_QUERIES}
    for i in range(samples_needed):
        for node, cfg in GPU_QUERIES.items():
            v = query_once(cfg["metric"], cfg["instance"])
            if v is not None:
                acc[node].append(v)
        time.sleep(SAMPLE_INTERVAL_SEC)
    avg = {}
    for node, vals in acc.items():
        if vals:
            avg[node] = sum(vals) / len(vals)
    print("📊 30s averages:", {k: round(v, 2) for k, v in avg.items()})
    return avg

def get_posture_pods():
    """Return list of dicts: {name, node, pi, phase} for posture pods only."""
    out = run("kubectl get pods -o json", capture=True, check=False)
    pods = []
    try:
        data = json.loads(out)
    except Exception:
        data = {"items": []}
    for item in data.get("items", []):
        name = item.get("metadata", {}).get("name", "")
        if not name.startswith(SCALEDJOB_NAME_PREFIX):
            continue
        node = item.get("spec", {}).get("nodeName", "")
        phase = item.get("status", {}).get("phase", "")
        m = re.search(r"scaledjob-(pi[\d-]+)-", name)  # pi2-3 etc.
        pi = m.group(1) if m else None
        pods.append({"name": name, "node": node, "pi": pi, "phase": phase})
    return pods

def delete_jobs_for_pi(pi):
    """Delete all Jobs for a given ScaledJob (deletes pods via controller)."""
    sj_name = PI_SCALEDJOBS[pi]
    out = run("kubectl get jobs -o name", capture=True, check=False)
    todo = []
    for line in out.splitlines():
        name = line.strip().split("/", 1)[-1]
        if name.startswith(sj_name + "-"):
            todo.append(name)
    if todo:
        run(["kubectl", "delete", "job"] + todo, check=False)
        for j in todo: print(f'   • job "{j}" deleted')

def delete_leftover_pods_for_pi(pi):
    sj_name = PI_SCALEDJOBS[pi]
    out = run("kubectl get pods -o name", capture=True, check=False)
    todo = []
    for line in out.splitlines():
        name = line.strip().split("/", 1)[-1]
        if name.startswith(sj_name + "-"):
            todo.append(name)
    if todo:
        run(["kubectl", "delete", "pod"] + todo, check=False)
        for p in todo: print(f'   • pod "{p}" deleted')

def patch_scaledjob_affinity(pi, target_node):
    sj_name = PI_SCALEDJOBS[pi]
    patch = {
        "spec": {
            "jobTargetRef": {
                "template": {
                    "spec": {
                        "affinity": {
                            "nodeAffinity": {
                                "requiredDuringSchedulingIgnoredDuringExecution": {
                                    "nodeSelectorTerms": [
                                        {"matchExpressions": [
                                            {"key": "gpu-node", "operator": "In", "values": [target_node]}
                                        ]}
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    run(["kubectl","patch","scaledjob",sj_name,"--type=merge","-p",json.dumps(patch)], check=False)

# ---------- Balancer loop ----------
def choose_destination(under_avg):
    """under_avg: dict(node->avg). Pick node with lowest avg; random tie-break."""
    min_val = min(under_avg.values())
    candidates = [n for n, v in under_avg.items() if v == min_val]
    return random.choice(candidates)

def main():
    print(f"🚦 gpu_balancer started with threshold={GPU_THRESHOLD}%")
    while True:
        print("⏳ Observing 30s window...")
        avg = sample_avg_usages()
        if not avg:
            print("⚠️ No metrics; sleeping 30s.")
            time.sleep(30)
            continue

        overloaded = {n: v for n, v in avg.items() if v > GPU_THRESHOLD}
        underloaded = {n: v for n, v in avg.items() if v <= GPU_THRESHOLD}

        if not overloaded:
            print("✅ Stable: no node over threshold. Sleeping 30s.")
            time.sleep(30)
            continue

        if not underloaded:
            print("🛑 All nodes overloaded; cannot offload. Sleeping 30s.")
            time.sleep(30)
            continue

        # One offload per overloaded node per loop
        pods = get_posture_pods()
        moved = 0
        for bad_node in overloaded.keys():
            # pick one running pod on the overloaded node
            cands = [p for p in pods if p["node"] == bad_node and p["phase"] == "Running" and p.get("pi")]
            if not cands:
                continue
            victim = cands[0]  # simple policy; could be oldest, random, etc.
            pi = victim["pi"]

            # choose destination (lowest avg among underloaded; tie random)
            dest = choose_destination(underloaded)
            print(f"🔁 Offloading one job for {pi}: {bad_node} → {dest}")

            # delete Job(s) first, then leftover pods (your convention)
            delete_jobs_for_pi(pi)
            delete_leftover_pods_for_pi(pi)

            # patch ScaledJob affinity to destination
            patch_scaledjob_affinity(pi, dest)
            moved += 1

        if moved == 0:
            print("ℹ️ Nothing to move this loop.")
        print("🛌 Sleep 30s before next check...")
        time.sleep(30)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"❌ gpu_balancer failed: {e}")
