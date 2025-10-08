

import os
import time
from datetime import datetime, timezone
from typing import Dict, List

from kubernetes import client, config
from kubernetes.client import V1Pod
from kubernetes.client.rest import ApiException

# Prometheus / node CPU helpers from your project
from cpu_metrics import (
    get_underloaded_nodes,  # -> (OrderedDict{ "IP:9100": used_pct (asc) }, { "IP": "nodeName" })
    get_node_cpu_usage,     # -> dict{ "IP:9100": used_pct }  (10s avg)
    strip_port,             # -> "IP" from "IP:9100"
)

# ----------------------------
# Tunables (env-overridable)
# ----------------------------
POD_NAMESPACE = os.getenv("POD_NAMESPACE", "default")
POD_LABEL_SELECTOR = os.getenv("POD_LABEL_SELECTOR", "app=posture")
SCHEDULING_INTERVAL_SECONDS = int(os.getenv("SCHEDULING_INTERVAL_SECONDS", "30"))
CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "90"))
SCHEDULER_NAME = os.getenv("SCHEDULER_NAME", "cpu-scheduler")

# Only act on pods older than this (avoid racing brand-new pods)
MIN_POD_AGE_SECONDS = int(os.getenv("MIN_POD_AGE_SECONDS", "5"))

# ----------------------------
# Kube config
# ----------------------------
def load_kube_config():
    """Prefer in-cluster (K3s), fall back to local kubeconfig for dev."""
    try:
        config.load_incluster_config()
        print("🔐 Using in-cluster Kubernetes config.")
    except Exception:
        config.load_kube_config()
        print("💻 Using local kubeconfig.")

# ----------------------------
# Pod utilities
# ----------------------------
def list_posture_pods() -> List[V1Pod]:
    v1 = client.CoreV1Api()
    items = v1.list_namespaced_pod(
        namespace=POD_NAMESPACE,
        label_selector=POD_LABEL_SELECTOR,
        watch=False,
    ).items
    # only pods that explicitly target our scheduler
    return [p for p in items if getattr(p.spec, "scheduler_name", None) == SCHEDULER_NAME]

def get_pending_pods() -> List[V1Pod]:
    return [
        p for p in list_posture_pods()
        if (p.status and p.status.phase == "Pending")
    ]

def get_running_pods() -> List[V1Pod]:
    return [
        p for p in list_posture_pods()
        if (p.status and p.status.phase == "Running")
    ]

def pod_age_seconds(p: V1Pod) -> float:
    ts = getattr(p.metadata, "creation_timestamp", None)
    if not ts:
        return 1e9
    return (datetime.now(timezone.utc) - ts).total_seconds()

# ----------------------------
# Placement helpers
# ----------------------------
def assign_evenly(pods: List[V1Pod], node_names: List[str]) -> Dict[str, str]:
    """Round-robin mapping of pod.name -> nodeName."""
    mapping: Dict[str, str] = {}
    if not node_names:
        return mapping
    i = 0
    for p in pods:
        mapping[p.metadata.name] = node_names[i % len(node_names)]
        i += 1
    return mapping

def label_pod_target_node(pod: V1Pod, node_name: str):
    """Optional: record the decision as a label (metadata is mutable)."""
    v1 = client.CoreV1Api()
    patch_body = {"metadata": {"labels": {"cpu-scheduler/target-node": node_name}}}
    try:
        v1.patch_namespaced_pod(
            name=pod.metadata.name,
            namespace=pod.metadata.namespace or POD_NAMESPACE,
            body=patch_body,
        )
        print(f"🏷️  Labeled {pod.metadata.name} with cpu-scheduler/target-node={node_name}")
    except ApiException as e:
        print(f"⚠️  Failed to label {pod.metadata.name}: {e}")

def bind_pod_to_node(pod_name: str, namespace: str, node_name: str):
    """Use the Pod Binding subresource to assign the pod to a node (and avoid client deserialization issues)."""
    if not node_name:
        raise ValueError(f"bind_pod_to_node: empty node_name for pod {pod_name}")

    v1 = client.CoreV1Api()
    body = client.V1Binding(
        metadata=client.V1ObjectMeta(name=pod_name),
        target=client.V1ObjectReference(api_version="v1", kind="Node", name=node_name),
    )
    try:
        # NOTE: _preload_content=False prevents the client from trying (and failing) to deserialize the response
        v1.create_namespaced_pod_binding(
            name=pod_name,
            namespace=namespace,
            body=body,
            _preload_content=False,
        )
        print(f"📌 Bound pod {pod_name} → node '{node_name}'")
    except ApiException as e:
        # 409: Already bound (race), 404: pod disappeared — both are safe to ignore
        if e.status in (409, 404):
            print(f"ℹ️  Bind skipped for {pod_name} (status {e.status}).")
            return
        print(f"❌ Bind error for {pod_name}: {e}")
        raise


def delete_pod_fast(pod: V1Pod):
    """Delete a pod quickly (offload from overloaded node)."""
    v1 = client.CoreV1Api()
    try:
        v1.delete_namespaced_pod(
            name=pod.metadata.name,
            namespace=pod.metadata.namespace or POD_NAMESPACE,
            grace_period_seconds=0,
        )
        print(f"🗑️  Deleted pod {pod.metadata.name} on node '{pod.spec.node_name}' (overloaded).")
    except ApiException as e:
        if e.status != 404:
            print(f"❌ Failed deleting pod {pod.metadata.name}: {e}")

# ----------------------------
# Scheduling passes
# ----------------------------
def initial_schedule():
    """Spread Pending pods across underloaded nodes; label; bind."""
    # Underloaded nodes and IP→node mapping
    underloaded_sorted, ip_to_node = get_underloaded_nodes(threshold=CPU_THRESHOLD)
    node_names = [ip_to_node[strip_port(ip)] for ip in underloaded_sorted.keys()]

    pending = [p for p in get_pending_pods() if pod_age_seconds(p) >= MIN_POD_AGE_SECONDS]
    if not pending:
        print("ℹ️  No (age-eligible) Pending pods to schedule.")
        return

    if not node_names:
        print("⚠️  No underloaded nodes below threshold; deferring scheduling this tick.")
        return

    plan = assign_evenly(pending, node_names)
    print(f"📦 Scheduling {len(pending)} Pending pods across {len(node_names)} underloaded nodes...")

    for p in pending:
        target = plan.get(p.metadata.name)
        if not target:
            continue
        # Optional label for observability (safe & mutable)
        label_pod_target_node(p, target)
        # Actual scheduling: bind the pod
        try:
            bind_pod_to_node(pod_name=p.metadata.name, namespace=POD_NAMESPACE, node_name=target)
        except ApiException as e:
            # benign: if controller already rescheduled or pod vanished
            print(f"⚠️  Bind failed for {p.metadata.name}: {e}")

def offload_overloaded_and_reschedule():
    """Delete Running pods from overloaded nodes; then schedule any new Pending pods."""
    usage_by_instance = get_node_cpu_usage()  # {"IP:9100": used_pct}
    underloaded_sorted, ip_to_node = get_underloaded_nodes(threshold=CPU_THRESHOLD)

    # Identify overloaded node names
    overloaded_nodes = set()
    for inst, used in usage_by_instance.items():
        if used >= CPU_THRESHOLD:
            n = ip_to_node.get(strip_port(inst))
            if n:
                overloaded_nodes.add(n)

    if overloaded_nodes:
        print(f"🚨 Overloaded nodes detected: {sorted(overloaded_nodes)}")
        # Delete running pods on those nodes
        for p in get_running_pods():
            if getattr(p.spec, "node_name", None) in overloaded_nodes:
                delete_pod_fast(p)
    else:
        print("✅ No overloaded nodes detected this tick.")

    # After deletion, new Pending pods will appear; schedule them:
    initial_schedule()

# ----------------------------
# Main control loop
# ----------------------------
def main():
    print("🚀 Starting CPU-aware scheduler (Binding + labeling, in-cluster ready)...")
    load_kube_config()

    # Initial pass
    initial_schedule()

    while True:
        pending = get_pending_pods()
        running = get_running_pods()

        if not pending and not running:
            print("🏁 All posture pods completed. Exiting.")
            break

        offload_overloaded_and_reschedule()

        print(f"⏳ Sleeping {SCHEDULING_INTERVAL_SECONDS}s ...")
        time.sleep(SCHEDULING_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
