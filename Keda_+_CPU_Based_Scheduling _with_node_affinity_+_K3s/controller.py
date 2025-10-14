# controller.py
import asyncio
import os
import random
from typing import Dict, List, Tuple

from fastapi import FastAPI, Request
from prometheus_api_client import PrometheusConnect
from kubernetes import client, config

# ---- Config ----
PROM_URL = os.getenv("PROM_URL", "http://localhost:9090")
CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "0.9"))
LABEL_KEY = "posture/eligible"
SLOT_KEY = "posture/slot"
NAMESPACE = os.getenv("NAMESPACE", "posture")
LABEL_LOOP_SECONDS = int(os.getenv("LABEL_LOOP_SECONDS", "10"))

# ---- Clients ----
prom = PrometheusConnect(url=PROM_URL, disable_ssl=True)
config.load_incluster_config()
v1 = client.CoreV1Api()

app = FastAPI()

def _prom_cpu_30s_by_instance() -> Dict[str, float]:
    query = '(1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[30s])))'
    results = prom.custom_query(query)
    node_cpu: Dict[str, float] = {}
    for r in results:
        ip = r["metric"]["instance"].split(":")[0]
        cpu = float(r["value"][1])
        node = resolve_node_name(ip)
        if node:
            node_cpu[node] = cpu
    return node_cpu

def resolve_node_name(ip: str) -> str | None:
    try:
        nodes = v1.list_node().items
        for node in nodes:
            for addr in node.status.addresses:
                if addr.type == "InternalIP" and addr.address == ip:
                    return node.metadata.name
    except Exception as e:
        print("Error resolving node name:", e)
    return None

def patch_node_label(node_name: str, key: str, value: str | None):
    body = {"metadata": {"labels": {key: (value if value is not None else None)}}}
    try:
        v1.patch_node(node_name, body)
    except Exception as e:
        print(f"Failed to label {node_name} ({key}={value}): {e}")

def list_all_node_names() -> List[str]:
    try:
        return [n.metadata.name for n in v1.list_node().items]
    except Exception as e:
        print("Error listing nodes:", e)
        return []

def rank_nodes_least_loaded(node_cpu: Dict[str, float]) -> List[Tuple[str, float]]:
    return sorted(node_cpu.items(), key=lambda x: (x[1], random.random()))

async def label_nodes_loop():
    while True:
        try:
            node_cpu = _prom_cpu_30s_by_instance()
            if not node_cpu:
                for node in list_all_node_names():
                    patch_node_label(node, LABEL_KEY, None)
                    patch_node_label(node, SLOT_KEY, None)
                await asyncio.sleep(LABEL_LOOP_SECONDS)
                continue

            eligible_nodes = [n for n, busy in node_cpu.items() if busy < CPU_THRESHOLD]
            N = len(eligible_nodes)

            ranked = rank_nodes_least_loaded(node_cpu)
            selected = [node for node, _ in ranked[:N]]

            all_nodes = set(list_all_node_names())
            selected_set = set(selected)

            for idx, node in enumerate(selected, start=1):
                patch_node_label(node, LABEL_KEY, "true")
                patch_node_label(node, SLOT_KEY, f"slot-{idx}")

            for node in all_nodes - selected_set:
                patch_node_label(node, LABEL_KEY, None)
                patch_node_label(node, SLOT_KEY, None)

            print(
                f"labeler: threshold={CPU_THRESHOLD:.2f} eligible={N} "
                f"selected={selected} ranked={[(n, round(b,3)) for n,b in ranked[:min(len(ranked),5)]]}..."
            )

        except Exception as e:
            print("Node labeling error:", e)

        await asyncio.sleep(LABEL_LOOP_SECONDS)

def find_analyzer_pod_on_node(node: str) -> str | None:
    try:
        pods = v1.list_namespaced_pod(namespace=NAMESPACE, label_selector="app=posture-analyzer").items
        for pod in pods:
            if pod.spec.node_name == node:
                return pod.metadata.name
    except Exception as e:
        print(f"Error listing pods on node {node}: {e}")
    return None

@app.post("/overload")
async def handle_overload(request: Request):
    """
    Receives: {"overloaded_nodes": ["10.0.0.12:9100", ...]}
    For each, resolve node and evict the analyzer pod running there.
    """
    try:
        data = await request.json()
        overloaded = data.get("overloaded_nodes", [])
        if not overloaded:
            print("⚠️  No overloaded nodes received.")
            return {"status": "no-action"}

        evicted = []

        for node_ip in overloaded:
            ip = node_ip.split(":")[0]
            node = resolve_node_name(ip)
            if not node:
                print(f"❌ Could not resolve node for IP: {ip}")
                continue

            pod_name = find_analyzer_pod_on_node(node)
            if not pod_name:
                print(f"ℹ️ No analyzer pod found on node {node}")
                continue

            print(f"🔥 Evicting pod {pod_name} from node {node}")
            try:
                v1.delete_namespaced_pod(name=pod_name, namespace=NAMESPACE)
                evicted.append({"node": node, "pod": pod_name})
            except Exception as e:
                print(f"❌ Failed to evict pod {pod_name} from {node}: {e}")

        return {"status": "ok", "evicted": evicted}

    except Exception as e:
        print(f"❌ Error in /overload: {e}")
        return {"status": "error", "message": str(e)}

@app.on_event("startup")
async def _start_labeler():
    asyncio.create_task(label_nodes_loop())
    print("controller: label_nodes_loop started")
