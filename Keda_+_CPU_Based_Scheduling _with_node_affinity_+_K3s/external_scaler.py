import os
import time
import grpc
import threading
import requests
import logging
from concurrent import futures
from external_scaler_pb2 import (
    GetMetricsResponse,
    MetricValue,
    IsActiveResponse,
    GetMetricSpecResponse,
    MetricSpec,
)
import external_scaler_pb2_grpc as externalscaler_pb2_grpc

# ---------------------------------------------------
# Configuration
# ---------------------------------------------------
CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "0.70"))
SCRAPE_INTERVAL = 30  # fast loop for KEDA admission
OVERLOAD_INTERVAL = 900  # 15 min = 900 seconds
PROM_URL = os.getenv("PROM_URL", "http://localhost:9090")
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://posture-controller.posture.svc.cluster.local:8081/overload")

CPU_QUERIES = {
    "agx-desktop": {"instance": "192.168.1.135:9100"},
    "orin-desktop": {"instance": "192.168.1.118:9100"},
    "orin1-desktop": {"instance": "192.168.1.77:9100"},
    "orin2-desktop": {"instance": "192.168.1.35:9100"},
    "nano1-desktop": {"instance": "192.168.1.193:9100"},
    "nano2-desktop": {"instance": "192.168.1.42:9100"},
}

# ---------------------------------------------------
# Logging setup
# ---------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------
# Helper: scrape short CPU usage (30s)
# ---------------------------------------------------
def scrape_cpu_usage(instance):
    url = f"http://{instance}/metrics"
    try:
        r = requests.get(url, timeout=3)
        r.raise_for_status()
        lines = r.text.splitlines()
        cpu_data = {}
        for line in lines:
            if line.startswith("node_cpu_seconds_total"):
                parts = line.split()
                if len(parts) != 2:
                    continue
                metric, value = parts
                if 'cpu="' not in metric or 'mode="' not in metric:
                    continue
                cpu = metric.split('cpu="')[1].split('"')[0]
                mode = metric.split('mode="')[1].split('"')[0]
                cpu_data.setdefault(cpu, {})[mode] = float(value)

        # Compute usage = 1 - idle/total
        total_idle = 0
        total_all = 0
        for cpu, stats in cpu_data.items():
            total = sum(stats.values())
            idle = stats.get("idle", 0)
            total_all += total
            total_idle += idle
        if total_all == 0:
            return None
        usage = 1 - (total_idle / total_all)
        return round(usage, 3)
    except Exception as e:
        logging.warning(f"Failed to scrape {instance}: {e}")
        return None

# ---------------------------------------------------
# Helper: Prometheus query for 15-minute overloads
# ---------------------------------------------------
def get_overloaded_nodes_15min(prom_url, cpu_threshold=0.7):
    query = '(1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[15m])))'
    try:
        r = requests.get(f"{prom_url}/api/v1/query", params={"query": query}, timeout=5)
        r.raise_for_status()
        data = r.json()["data"]["result"]
        overloaded = []
        for entry in data:
            instance = entry["metric"].get("instance")
            value = float(entry["value"][1])
            if value > cpu_threshold:
                overloaded.append(instance)
        return overloaded
    except Exception as e:
        logging.warning(f"⚠️ Failed 15m overload query: {e}")
        return []

# ---------------------------------------------------
# Overload monitor loop
# ---------------------------------------------------
def overload_monitor_loop():
    while True:
        try:
            overloaded = get_overloaded_nodes_15min(PROM_URL, CPU_THRESHOLD)
            if overloaded:
                logging.warning(f"🔥 Overloaded nodes (15m avg): {overloaded}")
                payload = {"overloaded_nodes": overloaded}
                try:
                    resp = requests.post(CONTROLLER_URL, json=payload, timeout=5)
                    if resp.ok:
                        logging.info(f"✅ Notified controller: {overloaded}")
                    else:
                        logging.error(f"❌ Controller rejected overload POST: {resp.status_code} {resp.text}")
                except Exception as post_err:
                    logging.error(f"❌ Failed to POST to controller: {post_err}")
            else:
                logging.info("🌿 No overloaded nodes in 15m avg.")
        except Exception as e:
            logging.error(f"Overload loop error: {e}")
        time.sleep(OVERLOAD_INTERVAL)

# ---------------------------------------------------
# Global metrics cache (updated in background)
# ---------------------------------------------------
node_usages = {}
available_nodes = 0

def update_node_usages_loop():
    global node_usages, available_nodes
    while True:
        current = {}
        available = 0
        for name, cfg in CPU_QUERIES.items():
            usage = scrape_cpu_usage(cfg["instance"])
            if usage is not None:
                current[name] = usage
                if usage < CPU_THRESHOLD:
                    available += 1
        node_usages = current
        available_nodes = available
        logging.info(f"Node CPU utilization: {current}")
        logging.info(f"Available nodes (usage < {CPU_THRESHOLD}): {available}")
        time.sleep(SCRAPE_INTERVAL)

# ---------------------------------------------------
# gRPC Scaler Service
# ---------------------------------------------------
class ExternalScaler(externalscaler_pb2_grpc.ExternalScalerServicer):
    def IsActive(self, request, context):
        active = available_nodes > 0
        logging.info(f"IsActive -> available={available_nodes}")
        return IsActiveResponse(result=active)

    def GetMetricSpec(self, request, context):
        metric_name = os.getenv("METRIC_NAME", "available_node_count_30s")
        logging.info(f"GetMetricSpec -> metric_name={metric_name}")
        return GetMetricSpecResponse(
            metric_specs=[
                MetricSpec(metric_name=metric_name, target_size=1)
            ]
        )

    def GetMetrics(self, request, context):
        metric_name = os.getenv("METRIC_NAME", "available_node_count_30s")
        value = available_nodes
        logging.info(f"GetMetrics({metric_name}) -> {value}")
        return GetMetricsResponse(
            metric_values=[
                MetricValue(metric_name=metric_name, metric_value=value)
            ]
        )

# ---------------------------------------------------
# Server setup
# ---------------------------------------------------
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    externalscaler_pb2_grpc.add_ExternalScalerServicer_to_server(ExternalScaler(), server)
    server.add_insecure_port("[::]:8080")
    server.start()
    logging.info("🚀 Prometheus External Scaler started on port 8080")
    server.wait_for_termination()

# ---------------------------------------------------
# Main entrypoint
# ---------------------------------------------------
if __name__ == "__main__":
    threading.Thread(target=update_node_usages_loop, daemon=True).start()
    threading.Thread(target=overload_monitor_loop, daemon=True).start()
    serve()
