#!/usr/bin/env python3
import json
import os
import random
import re
import subprocess
import sys
import time
from urllib.parse import quote

# ---------- Config ----------
PROMETHEUS_URL = "http://localhost:9090"
QUERY_ENDPOINT = "/api/v1/query"
GPU_THRESHOLD = 90.0  # not used for move logic; kept for parity
LAST_NODE_FILE = "last_node.txt"

# Your two Jetson workers + matching Prometheus metrics
GPU_QUERIES = {
    "agx-desktop": {
        "instance": "192.168.1.135:9100",
        "metric": "jetson_gpu_usage_percent",
    },
    "orin-desktop": {
        "instance": "192.168.1.118:9100",
        "metric": "jetson_orin_gpu_load_percent",
    },
}

# Names/prefixes used by your ScaledJobs/Jobs/Pods
PI_SCALEDJOBS = {
    "pi1": "posture-analyzer-scaledjob-pi1",
    "pi2": "posture-analyzer-scaledjob-pi2",
    "pi3": "posture-analyzer-scaledjob-pi3",
}
SCALEDJOB_NAME_PREFIX = "posture-analyzer-scaledjob-pi"  # for regex parsing

# ---------- Helpers ----------
def run(cmd, check=True, capture=False):
    if isinstance(cmd, str):
        shell = True
    else:
        shell = False
    try:
        if capture:
            out = subprocess.check_output(cmd, shell=shell, stderr=subprocess.STDOUT, text=True)
            return out
        else:
            subprocess.check_call(cmd, shell=shell)
            return ""
    except subprocess.CalledProcessError as e:
        if capture:
            print(e.output)
        if check:
            raise
        return ""

def query_prometheus(metric, instance):
    url = f"{PROMETHEUS_URL}{QUERY_ENDPOINT}?query={quote(f'{metric}{{instance=\"{instance}\"}}')}"
    print(f"🔍 Querying Prometheus: {url}")
    try:
        out = run(["curl", "-sS", url], capture=True)
        data = json.loads(out)
        if data.get("status") != "success":
            return None
        result = data.get("data", {}).get("result", [])
        if not result or not result[0].get("value"):
            return None
        value = float(result[0]["value"][1])
        return value
    except Exception as e:
        print(f"❌ Prometheus query failed for {instance}: {e}")
        return None

def pick_best_node():
    # lower GPU usage = better
    usages = {}
    for node, cfg in GPU_QUERIES.items():
        v = query_prometheus(cfg["metric"], cfg["instance"])
        if v is None:
            print(f"   • {node}: ❌ Unable to fetch GPU usage")
        else:
            usages[node] = v
            print(f"   • {node}: {v:.2f}% GPU used")
    if not usages:
        return None
    # choose the node with lowest usage; if tie, random
    best_val = min(usages.values())
    best_nodes = [n for n, v in usages.items() if v == best_val]
    return random.choice(best_nodes)

def read_last_node():
    if os.path.exists(LAST_NODE_FILE):
        return open(LAST_NODE_FILE).read().strip()
    return ""

def write_last_node(node):
    try:
        with open(LAST_NODE_FILE, "w") as f:
            f.write(node or "")
    except Exception as e:
        print(f"⚠️ Failed to write last node file: {e}")

def get_posture_pods():
    """
    Return list of dicts: {name, node, pi, phase}
    Only includes pods whose name starts with posture-analyzer-scaledjob-piX-
    """
    out = run("kubectl get pods -o json", capture=True, check=False)
    pods = []
    try:
        data = json.loads(out)
    except Exception:
        data = {"items": []}
    for item in data.get("items", []):
        name = item.get("metadata", {}).get("name", "")
        if not name.startswith(SCALEDJOB_NAME_PREFIX):
            continue
        node = item.get("spec", {}).get("nodeName", "")
        phase = item.get("status", {}).get("phase", "")
        m = re.search(r"scaledjob-(pi\d+)-", name)
        pi = m.group(1) if m else None
        pods.append({"name": name, "node": node, "pi": pi, "phase": phase})
    return pods

def count_pods_by_node(pods):
    cnt = {}
    for p in pods:
        node = p["node"] or ""
        cnt[node] = cnt.get(node, 0) + 1
    return cnt

def delete_jobs_for_pi(pi):
    """
    Delete ALL Jobs created from the given ScaledJob (cascade deletes its pods).
    We delete Jobs *first* (your requested change) before deleting any straggler pods.
    """
    sj_name = PI_SCALEDJOBS[pi]
    print(f"🗑️ Deleting Jobs for {sj_name} (if any)...")
    # list all jobs and filter by name prefix
    out = run("kubectl get jobs -o name", capture=True, check=False)
    job_names = []
    for line in out.splitlines():
        # job.batch/<name>
        name = line.strip().split("/", 1)[-1]
        if name.startswith(sj_name + "-"):
            job_names.append(name)
    if job_names:
        run(["kubectl", "delete", "job"] + job_names, check=False)
        for j in job_names:
            print(f'   • job "{j}" deleted')
    else:
        print("   • no matching Jobs to delete")

def delete_leftover_pods_for_pi(pi):
    sj_name = PI_SCALEDJOBS[pi]
    print(f"🧹 Deleting leftover pods for {sj_name} (if any)...")
    out = run("kubectl get pods -o name", capture=True, check=False)
    pod_names = []
    for line in out.splitlines():
        # pod/<name>
        name = line.strip().split("/", 1)[-1]
        if name.startswith(sj_name + "-"):
            pod_names.append(name)
    if pod_names:
        run(["kubectl", "delete", "pod"] + pod_names, check=False)
        for p in pod_names:
            print(f'   • pod "{p}" deleted')
    else:
        print("   • no matching Pods to delete")

def patch_scaledjob_affinity(pi, target_node):
    """
    Minimal patch: set required nodeAffinity for the chosen ScaledJob only.
    This avoids touching other ScaledJobs so we can migrate one workload at a time.
    """
    sj_name = PI_SCALEDJOBS[pi]
    print(f"✏️ Patching ScaledJob {sj_name} to pin on node '{target_node}'...")
    patch = {
        "spec": {
            "jobTargetRef": {
                "template": {
                    "spec": {
                        "affinity": {
                            "nodeAffinity": {
                                "requiredDuringSchedulingIgnoredDuringExecution": {
                                    "nodeSelectorTerms": [
                                        {
                                            "matchExpressions": [
                                                {
                                                    "key": "gpu-node",
                                                    "operator": "In",
                                                    "values": [target_node],
                                                }
                                            ]
                                        }
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    # apply patch
    run(
        [
            "kubectl",
            "patch",
            "scaledjob",
            sj_name,
            "--type=merge",
            "-p",
            json.dumps(patch),
        ],
        check=False,
    )

# ---------- Main single-iteration logic ----------
def main():
    print("🚀 GPU Affinity Watcher running once in loop mode...")
    # 1) Read current GPU usage and pick best node
    agx = query_prometheus(GPU_QUERIES["agx-desktop"]["metric"], GPU_QUERIES["agx-desktop"]["instance"])
    orin = query_prometheus(GPU_QUERIES["orin-desktop"]["metric"], GPU_QUERIES["orin-desktop"]["instance"])

    # Build usable dict
    usages = {}
    if agx is not None:
        usages["agx-desktop"] = agx
    if orin is not None:
        usages["orin-desktop"] = orin

    # If no data, nothing to do
    if not usages:
        print("❌ No capacity metrics available from Prometheus. Exiting watcher.")
        return

    # Decide best node (lowest usage; random tie-break)
    min_val = min(usages.values())
    candidates = [n for n, v in usages.items() if v == min_val]
    best_node = random.choice(candidates)
    print(f"🧠 Best node selected: {best_node}")

    last_node = read_last_node()
    if best_node == last_node or not last_node:
        # Write/update last node and exit without changes (one-at-a-time migration happens on change)
        if best_node != last_node:
            write_last_node(best_node)
        print("✅ Node unchanged or first run; skipping patch/deletion.")
        return

    # 2) Best node changed -> migrate ONE workload from non-best to best,
    #    BUT keep at least one pod on the non-best node.
    pods = get_posture_pods()
    by_node = count_pods_by_node(pods)
    print(f"📦 Current posture pods per node: {by_node}")

    # The node we want to pull from is the "other" node (previous best/current non-best)
    non_best = [n for n in GPU_QUERIES if n != best_node]
    non_best = non_best[0] if non_best else None

    if not non_best:
        print("⚠️ Could not resolve a non-best node. Skipping.")
        write_last_node(best_node)  # still update last-node to avoid loops
        return

    non_best_count = by_node.get(non_best, 0)
    best_count = by_node.get(best_node, 0)

    # We only move if non-best currently has >= 2 pods so that it keeps ≥ 1 after migration
    if non_best_count < 2:
        print(f"ℹ️ Non-best node '{non_best}' has < 2 posture pods ({non_best_count}); not migrating.")
        write_last_node(best_node)
        return

    # Choose ONE pod on non-best to move
    candidates = [p for p in pods if p["node"] == non_best]
    # Prefer running pods
    running = [p for p in candidates if p["phase"] == "Running"]
    target_pod = running[0] if running else (candidates[0] if candidates else None)
    if not target_pod or not target_pod.get("pi"):
        print("⚠️ No suitable posture pod found to migrate from non-best node.")
        write_last_node(best_node)
        return

    pi = target_pod["pi"]  # "pi1" | "pi2" | "pi3"
    sj_name = PI_SCALEDJOBS[pi]
    print(f"🎯 Will migrate {sj_name} from '{non_best}' → '{best_node}'")

    # 3) IMPORTANT: delete Job(s) first (your requirement), then clean up any leftover pods.
    delete_jobs_for_pi(pi)
    delete_leftover_pods_for_pi(pi)  # usually nothing remains after job deletion, but safe to try

    # 4) Patch ONLY that ScaledJob to pin it to the new best node
    patch_scaledjob_affinity(pi, best_node)

    # 5) Done. KEDA will create a fresh Job; the patched affinity will schedule the new pod on best_node.
    write_last_node(best_node)
    print("✅ One-at-a-time migration complete.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"❌ Watcher failed: {e}")
