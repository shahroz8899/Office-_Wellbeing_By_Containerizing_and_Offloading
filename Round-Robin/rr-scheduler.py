import os
import sys
import time
from kubernetes import client, config, watch

SCHEDULER_NAME = os.getenv("RR_SCHEDULER_NAME", "rr-scheduler")
# Comma-separated node names in the desired order
NODE_ORDER = [n.strip() for n in os.getenv("RR_NODE_ORDER", "").split(",") if n.strip()]

def load_config():
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()

def reconcile_node_order(v1):
    """Ensure every configured node exists & is Ready; warn if not."""
    existing = {n.metadata.name: n for n in v1.list_node().items}
    final = []
    for name in NODE_ORDER:
        node = existing.get(name)
        if not node:
            print(f"[rr] WARNING: node '{name}' not found; will skip", flush=True)
            continue
        # (Optional) ensure Ready
        conditions = {c.type: c.status for c in (node.status.conditions or [])}
        if conditions.get("Ready") != "True":
            print(f"[rr] WARNING: node '{name}' not Ready; will skip", flush=True)
            continue
        final.append(name)
    if not final:
        raise RuntimeError("RR_NODE_ORDER resolved to no usable nodes")
    print(f"[rr] using node order: {final}", flush=True)
    return final

def bind(v1, pod, node_name):
    # Prefer Binding API (works on k3s/k8s)
    target = client.V1ObjectReference(api_version="v1", kind="Node", name=node_name)
    meta   = client.V1ObjectMeta(name=pod.metadata.name, namespace=pod.metadata.namespace)
    body   = client.V1Binding(target=target, metadata=meta)
    v1.create_namespaced_binding(namespace=pod.metadata.namespace, body=body)

def main():
    load_config()
    v1 = client.CoreV1Api()
    nodes = reconcile_node_order(v1)

    # Simple in-memory index; for crash resilience you can persist to a ConfigMap.
    rr_idx = 0

    w = watch.Watch()
    print(f"[rr] scheduler '{SCHEDULER_NAME}' started", flush=True)
    while True:
        try:
            for event in w.stream(v1.list_pod_for_all_namespaces, timeout_seconds=60):
                pod = event.get("object")
                if not pod or not pod.spec:
                    continue
                # Only handle pods that explicitly request this scheduler
                if pod.spec.scheduler_name != SCHEDULER_NAME:
                    continue
                # Skip anything that isn't Pending
                phase = (pod.status and pod.status.phase) or "Pending"
                if phase != "Pending":
                    continue
                # Skip if already assigned
                if pod.spec.node_name:
                    continue
                # (Optional) gate by label if you only want to schedule certain pods
                # labels = pod.metadata.labels or {}
                # if labels.get("scheduling") != "rr":
                #     continue

                node = nodes[rr_idx % len(nodes)]
                rr_idx += 1
                try:
                    bind(v1, pod, node)
                    print(f"[rr] bound {pod.metadata.namespace}/{pod.metadata.name} -> {node}", flush=True)
                except Exception as e:
                    print(f"[rr] ERROR binding {pod.metadata.name}: {e}", flush=True)
        except Exception as outer:
            print(f"[rr] watch loop error: {outer}; retrying in 2s", flush=True)
            time.sleep(2)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[rr] fatal: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
