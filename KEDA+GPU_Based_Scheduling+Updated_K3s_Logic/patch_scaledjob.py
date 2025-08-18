import requests
import random
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
        print(f"❌ Failed to query {instance}: {e}")
    return None

def choose_best_node():
    usage_by_node = {}
    for node, config in GPU_QUERIES.items():
        usage = query_prometheus(config["metric"], config["instance"])
        if usage is not None:
            usage_by_node[node] = usage
            print(f"📊 {node} GPU Usage: {usage:.2f}%")

    if not usage_by_node:
        return None

    items = list(usage_by_node.items())
    random.shuffle(items)
    best_node = min(items, key=lambda x: x[1])[0]
    print(f"🧠 Selected `{best_node}` as best node (after random tie-break if needed)")
    return best_node

def patch_scaledjob_template(input_file, output_file, target_node):
    with open(input_file, "r") as f:
        content = f.read()

    if "affinity:" in content:
        print(f"⚠️ Skipping patch for {input_file}: affinity already present.")
        return

    patched = content.replace(
        "restartPolicy: Never",
        f"""restartPolicy: Never
        affinity:
          nodeAffinity:
            requiredDuringSchedulingIgnoredDuringExecution:
              nodeSelectorTerms:
              - matchExpressions:
                - key: gpu-node
                  operator: In
                  values:
                  - {target_node}"""
    )

    with open(output_file, "w") as f:
        f.write(patched)

    print(f"✅ Patched {input_file} → {output_file} with nodeAffinity to `{target_node}`")

if __name__ == "__main__":
    best_node = choose_best_node()
    if not best_node:
        print("❌ No node available with valid GPU metrics.")
        exit(1)

    # Patch all three Pi-specific ScaledJobs
    patch_scaledjob_template("posture-job-pi1.yaml", "patched-job-pi1.yaml", best_node)
    patch_scaledjob_template("posture-job-pi2.yaml", "patched-job-pi2.yaml", best_node)
    patch_scaledjob_template("posture-job-pi3.yaml", "patched-job-pi3.yaml", best_node)
