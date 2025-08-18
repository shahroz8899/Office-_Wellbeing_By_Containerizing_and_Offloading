import subprocess
import requests
import random
from urllib.parse import quote
import time
import os

PROMETHEUS_URL = "http://localhost:9090"
QUERY_ENDPOINT = "/api/v1/query"
LAST_NODE_FILE = "last_node.txt"

GPU_QUERIES = {
    "agx-desktop": {
        "instance": "192.168.1.135:9100",
        "metric": "jetson_gpu_usage_percent"
    },
    "orin-desktop": {
        "instance": "192.168.1.118:9100",
        "metric": "jetson_orin_gpu_load_percent"
    }
}

def query_prometheus(metric_name, instance):
    query = f'{metric_name}{{instance="{instance}"}}'
    url = f"{PROMETHEUS_URL}{QUERY_ENDPOINT}?query={quote(query)}"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        results = data.get("data", {}).get("result", [])
        if results:
            return float(results[0]["value"][1])
    except Exception as e:
        print(f"❌ Error querying Prometheus for {instance}: {e}")
    return None

def choose_best_node():
    usage_map = {}
    for node, config in GPU_QUERIES.items():
        usage = query_prometheus(config["metric"], config["instance"])
        if usage is not None:
            usage_map[node] = usage
            print(f"📊 {node}: {usage:.2f}% GPU used")

    if not usage_map:
        return None

    items = list(usage_map.items())
    random.shuffle(items)
    best_node = min(items, key=lambda x: x[1])[0]
    print(f"🧠 Best node selected: {best_node}")
    return best_node

def patch_scaledjob_to_node(node):
    print(f"✏️ Patching ScaledJob with affinity to {node}...")
    subprocess.run("python3 patch_scaledjob.py", shell=True)

# ⬇️ CHANGED: delete pods for EACH ScaledJob name (pi1, pi2, pi3)
def delete_running_pods():
    print("🛑 Deleting running posture-analyzer pods (all Pis)...")
    for sj in [
        "posture-analyzer-scaledjob-pi1",
        "posture-analyzer-scaledjob-pi2",
        "posture-analyzer-scaledjob-pi3",
    ]:
        delete_cmd = (
            f"kubectl get pods -l scaledjob.keda.sh/name={sj} "
            "--no-headers | awk '{print $1}' | xargs -r kubectl delete pod"
        )
        subprocess.run(delete_cmd, shell=True)

# ⬇️ CHANGED: apply the three patched job files instead of a non-existent single file
def apply_patched_jobs():
    print("📦 Applying patched posture-analyzer jobs for pi1/pi2/pi3...")
    subprocess.run("kubectl apply -f patched-job-pi1.yaml", shell=True)
    subprocess.run("kubectl apply -f patched-job-pi2.yaml", shell=True)
    subprocess.run("kubectl apply -f patched-job-pi3.yaml", shell=True)

def get_last_node():
    if os.path.exists(LAST_NODE_FILE):
        with open(LAST_NODE_FILE, "r") as f:
            return f.read().strip()
    return None

def set_last_node(node):
    with open(LAST_NODE_FILE, "w") as f:
        f.write(node)

if __name__ == "__main__":
    print("🚀 GPU Affinity Watcher running once in loop mode...")

    best_node = choose_best_node()
    if not best_node:
        print("❌ No available node found. Watcher exiting without changes.\n")
        exit(0)

    last_node = get_last_node()
    if best_node != last_node:
        patch_scaledjob_to_node(best_node)
        delete_running_pods()          # ⬅️ updated
        apply_patched_jobs()           # ⬅️ updated
        set_last_node(best_node)
        print("✅ Patch and reschedule complete. Exiting watcher.\n")
    else:
        print(f"✅ Node unchanged ({best_node}), skipping patch and deletion.\n")
