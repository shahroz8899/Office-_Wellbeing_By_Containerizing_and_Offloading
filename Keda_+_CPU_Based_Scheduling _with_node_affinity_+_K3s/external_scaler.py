# external_scaler.py
#
# Runs two servers:
# 1) gRPC External Scaler for KEDA (port 8080)
# 2) HTTP (FastAPI) helper endpoints (port 8088)
#
# Core logic: "allowed" = number of nodes whose 30s CPU avg is below CPU_THRESHOLD,
#             EXCLUDING any nodes listed in EXCLUDE_NODES (e.g., control plane).

import os
import threading
import time
from typing import Dict, List, Tuple

import requests
import grpc
from concurrent import futures

# Adjust these imports if your generated module names differ
import external_scaler_pb2 as pb2
import external_scaler_pb2_grpc as pb2_grpc

from fastapi import FastAPI
import uvicorn

# --------------- Config ---------------
PROM_URL = os.getenv("PROM_URL", "http://localhost:9090")
CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "0.70"))  # 0.70 = 70%
GRPC_PORT = int(os.getenv("GRPC_PORT", "8080"))
HTTP_PORT = int(os.getenv("HTTP_PORT", "8088"))
METRIC_NAME = os.getenv("METRIC_NAME", "available_node_count_30s")

# Comma-separated list of node names to exclude from eligibility/capacity (e.g., control plane)
EXCLUDE_NODES = set(
    s.strip() for s in os.getenv("EXCLUDE_NODES", "localhost").split(",") if s.strip()
)

# 30s CPU utilization per node (1 - idle)
PROMQL_30S_CPU = r'''1 - avg by (instance)(rate(node_cpu_seconds_total{mode="idle"}[30s]))'''

# --------------- Prometheus helpers ---------------
def prom_instant_query(prom_url: str, query: str) -> List[Dict]:
    r = requests.get(f"{prom_url}/api/v1/query", params={"query": query}, timeout=5)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {data}")
    return data.get("data", {}).get("result", [])

def get_node_cpu_map() -> Dict[str, float]:
    """
    Returns {node_name: cpu_fraction_over_30s}
    """
    out: Dict[str, float] = {}
    for row in prom_instant_query(PROM_URL, PROMQL_30S_CPU):
        inst = row["metric"].get("instance", "")
        node = inst.split(":")[0]  # "nodename:9100" -> "nodename"
        try:
            val = float(row["value"][1])
            out[node] = val
        except Exception:
            continue
    return out

def compute_allowed_and_eligible() -> Tuple[int, List[str], Dict[str, float]]:
    """
    Returns:
      allowed: int = # of non-excluded nodes whose cpu < threshold
      eligible_nodes: sorted list of those nodes
      cpu_map: {node: cpu}
    """
    cpu_map = get_node_cpu_map()
    eligible = [n for n, v in cpu_map.items() if v < CPU_THRESHOLD]
    # Exclude control-plane or any explicitly excluded nodes
    eligible = [n for n in eligible if n not in EXCLUDE_NODES]
    return len(eligible), sorted(eligible), cpu_map

# --------------- gRPC External Scaler (KEDA) ---------------
class ExternalScaler(pb2_grpc.ExternalScalerServicer):
    def IsActive(self, request, context):
        try:
            allowed, _, _ = compute_allowed_and_eligible()
            return pb2.IsActiveResponse(result=(allowed > 0))
        except Exception as e:
            context.set_details(str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            return pb2.IsActiveResponse(result=False)

    def StreamIsActive(self, request, context):
        poll = float(os.getenv("STREAM_POLL_SECONDS", "5"))
        prev = None
        while True:
            try:
                allowed, _, _ = compute_allowed_and_eligible()
                is_active = allowed > 0
                if is_active != prev:
                    yield pb2.IsActiveResponse(result=is_active)
                    prev = is_active
            except Exception:
                # On error, don't spam; just sleep and retry
                pass
            time.sleep(poll)

    def GetMetrics(self, request, context):
        try:
            allowed, _, _ = compute_allowed_and_eligible()
            metric = pb2.MetricValue(metricName=METRIC_NAME, metricValue=allowed)
            return pb2.GetMetricsResponse(metricValues=[metric])
        except Exception as e:
            context.set_details(str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            return pb2.GetMetricsResponse(metricValues=[])

# --------------- HTTP (FastAPI) helper ---------------
app = FastAPI(title="External Scaler (Local helper)")

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/eligible")
def eligible():
    allowed, elig, cpu_map = compute_allowed_and_eligible()
    rows = [
        {
            "node": n,
            "cpu30s": round(cpu_map.get(n, 0.0), 4),
            "eligible": n in elig,
            "excluded": n in EXCLUDE_NODES,
        }
        for n in sorted(cpu_map.keys())
    ]
    return {"threshold": CPU_THRESHOLD, "excluded": sorted(EXCLUDE_NODES), "nodes": rows}

@app.get("/allowed")
def allowed():
    allowed, elig, _ = compute_allowed_and_eligible()
    return {"allowed": allowed, "eligible": elig, "threshold": CPU_THRESHOLD, "excluded": sorted(EXCLUDE_NODES)}

def run_grpc():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    pb2_grpc.add_ExternalScalerServicer_to_server(ExternalScaler(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    server.start()
    print(f"[gRPC] External Scaler listening on :{GRPC_PORT}")
    server.wait_for_termination()

def run_http():
    print(f"[HTTP] Helper listening on :{HTTP_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="info")

if __name__ == "__main__":
    t = threading.Thread(target=run_grpc, daemon=True)
    t.start()
    run_http()
