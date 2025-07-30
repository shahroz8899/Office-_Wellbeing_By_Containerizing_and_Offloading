import time
import subprocess
import requests
from urllib.parse import quote

PROMETHEUS_URL = "http://localhost:9090"
QUERY_ENDPOINT = "/api/v1/query"
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

CHECK_INTERVAL = 2  # seconds
last_node_used = None

def query_gpu_usage(node, config):
    query = f'{config["metric"]}{{instance="{config["instance"]}"}}'
    url = f"{PROMETHEUS_URL}{QUERY_ENDPOINT}?query={quote(query)}"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        results = data.get("data", {}).get("result", [])
        if results:
            return float(results[0]["value"][1])
    except Exception as e:
        print(f"❌ Error querying {node}: {e}")
    return None

def choose_best_node():
    usage_map = {}
    for node, config in GPU_QUERIES.items():
        usage = query_gpu_usage(node, config)
        if usage is not None:
            usage_map[node] = usage
            print(f"📊 {node}: {usage:.2f}% GPU used")
    if not usage_map:
        return None
    return min(usage_map, key=usage_map.get)

def patch_scaledjob_to_node(node):
    print(f"✏️ Patching ScaledJob with affinity to {node}...")
    subprocess.run(f"python3 patch_scaledjob.py {node}", shell=True)

if __name__ == "__main__":
    print("🔁 Starting GPU watcher loop to update nodeAffinity dynamically...\n")

    while True:
        try:
            best_node = choose_best_node()
            if best_node and best_node != last_node_used:
                patch_scaledjob_to_node(best_node)
                last_node_used = best_node
            else:
                print(f"✅ No change needed. Continuing with `{last_node_used}`...\n")
        except Exception as e:
            print(f"⚠️ Watcher error: {e}")
        time.sleep(CHECK_INTERVAL)
