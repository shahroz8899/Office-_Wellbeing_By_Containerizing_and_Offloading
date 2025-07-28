import subprocess
import time
import requests
from urllib.parse import quote

PROMETHEUS_URL = "http://localhost:9090"
QUERY_ENDPOINT = "/api/v1/query"

# GPU metric configuration per worker node
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

GPU_THRESHOLD = 60

def query_prometheus(metric_name, instance):
    query = f'{metric_name}{{instance="{instance}"}}'
    encoded_query = quote(query)
    url = f"{PROMETHEUS_URL}{QUERY_ENDPOINT}?query={encoded_query}"
    print(f"🔍 Querying Prometheus: {url}")
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        results = data.get("data", {}).get("result", [])
        if results:
            value = float(results[0]["value"][1])
            return value
    except Exception as e:
        print(f"❌ Error querying Prometheus for {instance}: {e}")
    return None

def get_available_worker_with_max_gpu():
    underloaded = []
    for node, config in GPU_QUERIES.items():
        usage = query_prometheus(config["metric"], config["instance"])
        if usage is not None:
            print(f"🔎 {node} GPU usage: {usage:.2f}%")
            if usage < GPU_THRESHOLD:
                underloaded.append((node, usage))
        else:
            print(f"⚠️ Unable to fetch GPU for {node}")
    
    if not underloaded:
        return None
    
    return sorted(underloaded, key=lambda x: x[1])[0][0]  # least used GPU

def launch_job_on_node(node_name):
    job_name = f"posture-analyzer-{int(time.time())}"
    print(f"🚀 Launching job {job_name} on {node_name}")

    with open("posture-job.yaml") as f:
        template = f.read()

    patched = (
        template
        .replace("name: posture-analyzer", f"name: {job_name}")
        .replace(
            "restartPolicy: Never",
            f"restartPolicy: Never\n      nodeName: {node_name}"
        )
    )

    with open("patched-job.yaml", "w") as f:
        f.write(patched)

    subprocess.run("kubectl apply -f patched-job.yaml", shell=True)

# Offloading loop
current_node = None
job_launched = False

while True:
    if current_node is None:
        selected = get_available_worker_with_max_gpu()
        if selected:
            current_node = selected
            launch_job_on_node(current_node)
            job_launched = True
        else:
            print("⚠️ No worker with available GPU. Retrying...")
    else:
        usage = query_prometheus(GPU_QUERIES[current_node]["metric"], GPU_QUERIES[current_node]["instance"])
        if usage is None or usage >= GPU_THRESHOLD:
            print(f"⚠️ Node {current_node} GPU now overloaded ({usage}%). Releasing...")
            current_node = None
            job_launched = False
        elif not job_launched:
            launch_job_on_node(current_node)
            job_launched = True
        else:
            print(f"✅ Waiting… Node {current_node} still under {usage:.2f}%. No new job launched.")

    time.sleep(5)
