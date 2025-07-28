import subprocess
import os
import signal
import time

def run_command(command):
    print(f"🔧 Running: {command}")
    subprocess.run(command, shell=True)

def kill_cpu_monitor():
    print("🛑 Looking for 'cpu_monitor_and_offload.py' process to terminate...")
    try:
        # List all running processes and filter for our script
        result = subprocess.check_output("ps aux | grep cpu_monitor_and_offload.py | grep -v grep", shell=True).decode()
        lines = result.strip().split("\n")
        for line in lines:
            if 'cpu_monitor_and_offload.py' in line:
                pid = int(line.split()[1])
                os.kill(pid, signal.SIGTERM)
                print(f"✅ Killed CPU monitor process (PID: {pid})")
    except Exception as e:
        print(f"⚠️ Failed to find or kill CPU monitor process: {e}")

def stop_everything():
    print("⛔ Stopping Docker containers...")
    run_command("docker-compose down")

    print("🧼 Deleting Kubernetes job...")
    run_command("kubectl get jobs --no-headers | awk '/^posture-analyzer-/ {print $1}' | xargs -r kubectl delete job")

    kill_cpu_monitor()
    print("✅ All services and background monitors stopped.")

if __name__ == "__main__":
    print("🟡 Press ENTER at any time to stop everything...")
    input()  # Waits for ENTER key
    stop_everything()
