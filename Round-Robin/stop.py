#!/usr/bin/env python3
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

def run(command, ignore_error=False):
    print(f"🔧 Running: {command}", flush=True)
    try:
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        if not ignore_error:
            raise
        print(f"⚠️ Ignored error: {e}", flush=True)

def delete_by_prefix(kind, prefix):
    run(
        f"kubectl get {kind} -A -o name 2>/dev/null | "
        f"awk -F'/' '/{prefix}/{{print $2}}' | "
        f"xargs -r kubectl delete {kind}",
        ignore_error=True,
    )

def copy_csv_from_pods():
    print("📥 Downloading result CSVs from all posture pods...", flush=True)
    try:
        result = subprocess.run(
            "kubectl get pods -o jsonpath='{.items[*].metadata.name}'",
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        pod_names = result.stdout.strip("'").split()

        for pod in pod_names:
            if not pod.startswith("posture-pi1"):
                continue

            # Guess CSV filename from pod name
            suffix = pod.replace("posture-", "")
            csv_file = f"{suffix}_results.csv"
            local_dir = Path("results") / pod
            local_dir.mkdir(parents=True, exist_ok=True)
            dest = local_dir / csv_file

            print(f"📦 Copying {csv_file} from pod {pod}...", flush=True)
            cp_cmd = f"kubectl cp default/{pod}:/app/{csv_file} {dest}"
            try:
                subprocess.run(cp_cmd, shell=True, check=True)
                print(f"✅ Saved to {dest}")
            except subprocess.CalledProcessError:
                print(f"⚠️ Failed to copy {csv_file} from pod {pod} (might have failed or exited).")
    except Exception as e:
        print(f"❌ Could not fetch pod list: {e}", flush=True)

def stop_everything():
    copy_csv_from_pods()

    print("⛔ Stopping Docker containers...", flush=True)
    run("docker-compose down", ignore_error=True)

    print("🧼 Deleting all posture Jobs...", flush=True)
    delete_by_prefix("job", "posture-pi1")

    print("🗑️ Deleting posture Pods...", flush=True)
    delete_by_prefix("pod", "posture-pi1")

    print("🧼 Deleting ScaledJobs (if any)...", flush=True)
    delete_by_prefix("scaledjob", "posture-pi1")

    print("🧽 Untainting master node (nuc) to restore normal scheduling...", flush=True)
    run("kubectl taint nodes nuc node-role.kubernetes.io/master- --overwrite || true", ignore_error=True)

    print("🧹 Optional: delete rr-scheduler deployment? (y/n): ", end="", flush=True)
    try:
        choice = input().strip().lower()
        if choice == "y":
            run("kubectl delete deployment rr-scheduler -n kube-system", ignore_error=True)
            run("kubectl delete serviceaccount rr-scheduler -n kube-system", ignore_error=True)
            run("kubectl delete clusterrole rr-scheduler", ignore_error=True)
            run("kubectl delete clusterrolebinding rr-scheduler", ignore_error=True)
    except EOFError:
        print("\n(no input available — skipping scheduler cleanup)", flush=True)

def wait_for_enter_or_signal():
    try:
        if sys.stdin and sys.stdin.isatty():
            print("🟡 Press ENTER at any time to stop everything...", flush=True)
            input()
            return "enter"
    except EOFError:
        pass

    try:
        with open("/dev/tty", "r") as tty:
            print("🟡 Press ENTER at any time to stop everything...", flush=True)
            tty.readline()
            return "enter-tty"
    except Exception:
        pass

    stopped = {"flag": False}
    def _handler(signum, frame):
        stopped["flag"] = True
    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
    print("🟡 No interactive stdin detected; waiting for Ctrl+C or SIGTERM to stop...", flush=True)
    while not stopped["flag"]:
        time.sleep(0.5)
    return "signal"

if __name__ == "__main__":
    try:
        reason = wait_for_enter_or_signal()
    except KeyboardInterrupt:
        reason = "kbint"
    stop_everything()
    print(f"✅ Stopped (trigger: {reason}).", flush=True)
