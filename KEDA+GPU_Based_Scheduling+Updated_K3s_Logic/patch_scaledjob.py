# patch_scaledjob.py
import requests, random, os, json
from urllib.parse import quote

PROMETHEUS_URL = "http://localhost:9090"
QUERY_ENDPOINT = "/api/v1/query"

# Nodes and their Prometheus metric/instance
GPU_QUERIES = {
    "agx-desktop": {"instance": "192.168.1.135:9100", "metric": "jetson_gpu_usage_percent"},
    "orin-desktop": {"instance": "192.168.1.118:9100", "metric": "jetson_orin_gpu_load_percent"},
    "orin1-desktop": {"instance": "192.168.1.77:9100", "metric": "jetson_orin1_gpu_usage_percent"},
    "orin2-desktop": {"instance": "192.168.1.35:9100", "metric": "jetson_orin2_gpu_usage_percent"},
    "orin3-desktop": {"instance": "192.168.1.XX:9100", "metric": "jetson_orin3_gpu_usage_percent"},  # TODO: real IP
    "nano1-desktop": {"instance": "192.168.1.193:9100", "metric": "jetson_nano1_gpu_usage_percent"},
    "nano2-desktop": {"instance": "192.168.1.42:9100", "metric": "jetson_nano2_gpu_usage_percent"},
}

# All ScaledJobs you want to place initially (input -> output)
SCALEDJOBS = [
    ("posture-job-pi1.yaml",   "patched-job-pi1.yaml"),
    ("posture-job-pi1-1.yaml", "patched-job-pi1-1.yaml"),
    ("posture-job-pi1-2.yaml", "patched-job-pi1-2.yaml"),
    ("posture-job-pi1-3.yaml", "patched-job-pi1-3.yaml"),
    ("posture-job-pi1-4.yaml", "patched-job-pi1-4.yaml"),
    ("posture-job-pi2.yaml",   "patched-job-pi2.yaml"),
    ("posture-job-pi2-1.yaml", "patched-job-pi2-1.yaml"),
    ("posture-job-pi2-2.yaml", "patched-job-pi2-2.yaml"),
    ("posture-job-pi2-3.yaml", "patched-job-pi2-3.yaml"),
    ("posture-job-pi2-4.yaml", "patched-job-pi2-4.yaml"),
    ("posture-job-pi3.yaml",   "patched-job-pi3.yaml"),
]

def q(metric, instance):
    url = f"{PROMETHEUS_URL}{QUERY_ENDPOINT}?query={quote(f'{metric}{{instance=\"{instance}\"}}')}"
    try:
        r = requests.get(url, timeout=5)
        d = r.json()
        res = d.get("data", {}).get("result", [])
        if res:
            return float(res[0]["value"][1])
    except Exception as e:
        print(f"❌ query failed for {instance}: {e}")
    return None

def get_node_usages():
    usages = {}
    for node, cfg in GPU_QUERIES.items():
        v = q(cfg["metric"], cfg["instance"])
        if v is not None:
            usages[node] = v
            print(f"📊 {node}: {v:.2f}% GPU used")
        else:
            print(f"⚠️ {node}: no metric; skipping for initial placement")
    return usages

def inject_affinity(yaml_text, node):
    if "affinity:" in yaml_text:
        # Replace existing requiredDuringSchedulingIgnoredDuringExecution block for gpu-node
        # For simplicity, just force-merge by appending/overwriting after restartPolicy
        pass
    patched = yaml_text.replace(
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
                  - {node}"""
    )
    return patched

def main():
    usages = get_node_usages()
    nodes = list(usages.keys())
    if not nodes:
        print("❌ No nodes with metrics; cannot plan initial spread.")
        raise SystemExit(1)

    # Sort nodes by current usage ascending (lowest = most attractive)
    # Also keep groups for tie-breaking
    by_usage = {}
    for n, u in usages.items():
        by_usage.setdefault(u, []).append(n)
    sorted_usages = sorted(by_usage.keys())

    # Plan even spread
    N = len(SCALEDJOBS)
    M = len(nodes)
    base = N // M
    extra = N % M

    # Build a placement queue per node: each node gets 'base' items;
    # distribute 'extra' to lowest-usage nodes; ties random.
    placement = {n: 0 for n in nodes}
    for n in nodes:
        placement[n] = base

    # Distribute extras to the lowest-usage nodes first
    # For each usage bucket in ascending order, randomly shuffle nodes and allocate remainder
    to_assign = extra
    for usage in sorted_usages:
        bucket = by_usage[usage][:]
        random.shuffle(bucket)  # random tie-break within same usage
        for n in bucket:
            if to_assign <= 0:
                break
            placement[n] += 1
            to_assign -= 1
        if to_assign <= 0:
            break

    print(f"🧮 Planned initial spread: {placement}")

    # Build a flat list of node "slots" respecting placement counts,
    # but prefer to assign each ScaledJob in rounds to improve evenness.
    node_slots = []
    max_count = max(placement.values())
    for i in range(max_count):
        # in each round, add all nodes that still need slots; to bias to low-usage, iterate nodes ordered by usage asc
        ordered_nodes = []
        for usage in sorted_usages:
            bucket = by_usage[usage][:]
            random.shuffle(bucket)  # break ties randomly each round
            ordered_nodes.extend(bucket)
        for n in ordered_nodes:
            if placement.get(n, 0) > 0:
                node_slots.append(n)
                placement[n] -= 1

    if len(node_slots) != N:
        print(f"⚠️ internal planning mismatch: slots={len(node_slots)} vs jobs={N}")

    # Patch each ScaledJob YAML with the chosen node
    for (inp, outp), node in zip(SCALEDJOBS, node_slots):
        with open(inp, "r") as f:
            txt = f.read()
        patched = inject_affinity(txt, node)
        with open(outp, "w") as f:
            f.write(patched)
        print(f"✅ {inp} → {outp} pinned to `{node}`")

if __name__ == "__main__":
    main()
