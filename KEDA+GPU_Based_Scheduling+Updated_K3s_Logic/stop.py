#!/usr/bin/env python3
import glob
import os
import signal
import subprocess

def run(command, ignore_error=False):
    print(f"🔧 Running: {command}")
    try:
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        if not ignore_error:
            raise
        print(f"⚠️ Command failed (but continuing): {e}")

def pkill(pattern, sig=signal.SIGTERM):
    print(f"🛑 pkill -f '{pattern}'")
    try:
        # Use numeric signal for portability (e.g., 15 = SIGTERM)
        subprocess.run(f"pkill -f -{sig.value} '{pattern}'", shell=True, check=False)
    except Exception as e:
        print(f"⚠️ pkill failed for {pattern}: {e}")

def kill_by_port(port, sig=signal.SIGTERM):
    print(f"🛑 Killing processes listening on :{port}")
    # Prefer lsof if present; otherwise fall back to ss
    if subprocess.run("command -v lsof >/dev/null 2>&1", shell=True).returncode == 0:
        run(f"lsof -t -i :{port} | xargs -r kill -{sig.value}", ignore_error=True)
    else:
        run(
            "ss -lptn 'sport = :{p}' | awk -F',' 'NR>1{{print $3}}' | "
            "awk -F'pid=' '{{print $2}}' | awk '{{print $1}}' | "
            f"xargs -r kill -{sig.value}".format(p=port),
            ignore_error=True,
        )

def delete_by_prefix(kind, prefix):
    # Delete any K8s object whose resource name contains the prefix
    run(
        f"kubectl get {kind} -o name 2>/dev/null | "
        f"awk -F'/' '/{prefix}/{{print $2}}' | "
        f"xargs -r kubectl delete {kind}",
        ignore_error=True,
    )

def stop_everything():
    print("⛔ Stopping Docker containers...")
    run("docker-compose down", ignore_error=True)

    print("🛑 Killing monitor/watcher processes...")
    pkill("cpu_monitor_and_offload.py")   # External Scaler + Prometheus polling
    pkill("gpu_balancer.py")     # Node watcher / rebalancer
    kill_by_port(50051)                  # gRPC External Scaler port (safety)

    print("🧼 Deleting posture-analyzer Jobs first...")
    delete_by_prefix("job", "posture-analyzer-")

    print("🗑️ Deleting leftover posture-analyzer Pods...")
    delete_by_prefix("pod", "posture-analyzer-")

    print("🧼 Deleting posture-analyzer ScaledJobs...")
    delete_by_prefix("scaledjob", "posture-analyzer-")

    print("🧹 Cleaning patched YAMLs...")
    for path in glob.glob("patched-job-*.yaml"):
        try:
            os.remove(path)
            print(f"🧽 Removed {path}")
        except Exception as e:
            print(f"⚠️ Could not remove {path}: {e}")

    print("🧽 Untainting master node (nuc) to restore normal scheduling...")
    run("kubectl taint nodes nuc node-role.kubernetes.io/master- --overwrite || true", ignore_error=True)

    print("✅ All jobs, pods, ScaledJobs, and watchers stopped.")

if __name__ == "__main__":
    try:
        print("🟡 Press ENTER at any time to stop everything...")
        input()
    except KeyboardInterrupt:
        pass
    stop_everything()
