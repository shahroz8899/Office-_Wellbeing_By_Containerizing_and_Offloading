import subprocess
import os
import signal

def run_command(command, ignore_error=False):
    print(f"🔧 Running: {command}")
    try:
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        if not ignore_error:
            raise
        print(f"⚠️ Command failed (but continuing): {e}")

def kill_process_by_name(script_name, label):
    print(f"🛑 Looking for '{script_name}' process to terminate...")
    try:
        result = subprocess.check_output(f"ps aux | grep {script_name} | grep -v grep", shell=True).decode()
        lines = result.strip().split("\n")
        for line in lines:
            if script_name in line:
                pid = int(line.split()[1])
                os.kill(pid, signal.SIGTERM)
                print(f"✅ Killed {label} process (PID: {pid})")
    except Exception as e:
        print(f"⚠️ Failed to find or kill {label} process: {e}")

def delete_patched_yaml():
    if os.path.exists("patched-job.yaml"):
        try:
            os.remove("patched-job.yaml")
            print("🧹 Removed old patched-job.yaml")
        except Exception as e:
            print(f"⚠️ Could not delete patched-job.yaml: {e}")

def stop_everything():
    print("⛔ Stopping Docker containers...")
    run_command("docker-compose down", ignore_error=True)

    print("🛑 Killing CPU monitor and gRPC scaler...")
    kill_process_by_name("cpu_monitor_and_offload.py", "CPU monitor")
    kill_process_by_name("gpu_affinity_watcher.py", "GPU watcher")

    print("🧼 Deleting all posture-analyzer jobs...")
    run_command("kubectl get jobs --no-headers | awk '/^posture-analyzer/ {print $1}' | xargs -r kubectl delete job", ignore_error=True)

    print("🧼 Deleting all posture-analyzer pods...")
    run_command("kubectl get pods --no-headers | awk '/^posture-analyzer/ {print $1}' | xargs -r kubectl delete pod", ignore_error=True)

    print("🧼 Deleting the ScaledJob...")
    run_command("kubectl delete scaledjob posture-analyzer-scaledjob", ignore_error=True)

    print("🧽 Untainting master node (nuc) to restore normal scheduling...")
    run_command("kubectl taint nodes nuc node-role.kubernetes.io/master- --overwrite || true")

    delete_patched_yaml()
    print("✅ All jobs, pods, and watchers stopped.")

if __name__ == "__main__":
    print("🟡 Press ENTER at any time to stop everything...")
    input()
    stop_everything()
