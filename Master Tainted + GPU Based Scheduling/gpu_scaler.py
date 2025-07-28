import time
import requests
from urllib.parse import quote

PROMETHEUS_URL = "http://localhost:9090"
QUERY_ENDPOINT = "/api/v1/query"

# Mapping of instance IPs to readable node names and Prometheus metric queries
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

def monitor_gpu_usage(interval=5):
    print("📊 GPU Usage per Worker Node:")
    try:
        while True:
            for node, config in GPU_QUERIES.items():
                usage = query_prometheus(config["metric"], config["instance"])
                if usage is not None:
                    print(f"✅ {node} → {usage:.2f}% GPU in use")
                else:
                    print(f"⚠️ {node} → Unable to fetch GPU usage")
            print("⏳ Waiting...\n")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("🛑 Monitoring stopped.")

if __name__ == "__main__":
    monitor_gpu_usage()
