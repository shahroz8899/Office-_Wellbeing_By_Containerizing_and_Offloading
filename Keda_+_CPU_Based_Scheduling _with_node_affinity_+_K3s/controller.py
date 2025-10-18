# controller.py — Ranker (fixed to avoid labeling non-existent/excluded nodes)
import os, threading, time, requests
from typing import Dict, List
from fastapi import FastAPI
import uvicorn

from kubernetes import client, config

PROM_URL = os.getenv("PROM_URL", "http://localhost:9090")
CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "0.70"))
EXCLUDE_NODES = set(s.strip() for s in os.getenv("EXCLUDE_NODES", "localhost").split(",") if s.strip())
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "10"))

PROMQL_30S_CPU = r'''1 - avg by (instance)(rate(node_cpu_seconds_total{mode="idle"}[30s]))'''

app = FastAPI(title="Posture Controller (Ranker)")
_last_state: Dict = {}

@app.get("/healthz")
def healthz():
    return {"ok": True, "threshold": CPU_THRESHOLD, "excluded": sorted(EXCLUDE_NODES)}

@app.get("/last")
def last():
    return _last_state or {}

def prom_query_instant(url: str, q: str) -> List[Dict]:
    r = requests.get(f"{url}/api/v1/query", params={"query": q}, timeout=5)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {data}")
    return data.get("data", {}).get("result", [])

def get_cpu_map_from_prom() -> Dict[str, float]:
    out: Dict[str, float] = {}
    for row in prom_query_instant(PROM_URL, PROMQL_30S_CPU):
        inst = row["metric"].get("instance", "")
        host = inst.split(":")[0]
        try:
            out[host] = float(row["value"][1])
        except Exception:
            continue
    return out

def load_kube():
    config.load_kube_config()  # running on NUC
    return client.CoreV1Api()

def ip_to_nodename_map(v1: client.CoreV1Api) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for n in v1.list_node().items:
        name = n.metadata.name
        addrs = n.status.addresses or []
        for a in addrs:
            if a.type in ("InternalIP", "Hostname"):
                mapping[a.address] = name
        mapping[name] = name  # allow direct name match
    return mapping

def label_node(v1: client.CoreV1Api, node: str, key: str, value: str):
    body = {"metadata": {"labels": {key: value}}}
    v1.patch_node(node, body)

def ranker_loop():
    global _last_state
    v1 = load_kube()

    # NEW: cache the set of valid Kubernetes node names to avoid 404s
    def current_node_name_set() -> set:
        return {n.metadata.name for n in v1.list_node().items}

    while True:
        try:
            raw_cpu = get_cpu_map_from_prom()
            ip2name = ip_to_nodename_map(v1)
            k8s_nodes = current_node_name_set()

            # Translate Prom hosts -> k8s node names; drop unknown hosts
            cpu_by_node: Dict[str, float] = {}
            for host, val in raw_cpu.items():
                node = ip2name.get(host)  # None if we can't map
                if node and node in k8s_nodes:
                    cpu_by_node[node] = val

            # Compute eligible set: under threshold, not excluded, and real k8s node
            eligible_nodes = [n for n, v in cpu_by_node.items()
                              if v < CPU_THRESHOLD and n not in EXCLUDE_NODES]

            # Sort by CPU ascending for ranks
            ranked = sorted(((n, cpu_by_node[n]) for n in eligible_nodes), key=lambda x: x[1])

            # Apply labels — ONLY to real nodes and NOT excluded
            for i, (node, _) in enumerate(ranked, start=1):
                label_node(v1, node, "posture/eligible", "true")
                label_node(v1, node, "posture/rank", str(i))

            # For all other *real* nodes (including excluded or over-threshold):
            for node in (k8s_nodes - {n for n, _ in ranked}):
                # Skip labeling excluded nodes entirely (don’t touch control plane)
                if node in EXCLUDE_NODES:
                    continue
                label_node(v1, node, "posture/eligible", "false")
                label_node(v1, node, "posture/rank", "9999")

            _last_state = {
                "eligible_count": len(ranked),
                "eligible_nodes": [n for n, _ in ranked],
                "excluded": sorted(EXCLUDE_NODES),
                "cpu_by_node": {n: round(v, 4) for n, v in sorted(cpu_by_node.items())},
            }
            print(f"[ranker] eligible={len(ranked)} nodes -> {', '.join(_last_state['eligible_nodes'])}")

        except Exception as e:
            print(f"[ranker] error: {e}")

        time.sleep(POLL_SECONDS)

def start():
    t = threading.Thread(target=ranker_loop, daemon=True)
    t.start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("CONTROLLER_PORT", "8090")))

if __name__ == "__main__":
    start()
