import subprocess
import time

def run_command(command, ignore_errors=False):
    try:
        print(f"👉 Running: {command}")
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        if ignore_errors:
            print(f"⚠️ Ignored error: {e}")
        else:
            print(f"❌ Command failed: {e}")
            exit(1)

if __name__ == "__main__":
    print("🔄 Stopping and removing any running container...")
    run_command("docker-compose down", ignore_errors=True)

    print("🧽 Force removing any leftover posture-analyzer container...")
    run_command("docker rm -f posture-analyzer", ignore_errors=True)

    print("🧹 Removing old Docker image...")
    run_command("docker rmi shahroz90/posture-analyzer", ignore_errors=True)

    print("🔨 Building multi-architecture Docker image and pushing to Docker Hub...")
    run_command("docker buildx build --platform linux/amd64,linux/arm64 -t shahroz90/posture-analyzer:latest --push .")

    print("✅ Docker setup complete.")

    print("📡 Launching CPU monitor and ESC listener in parallel...")

    print("🛡️ Tainting master node (nuc) to repel posture jobs...")
    run_command("kubectl taint nodes nuc node-role.kubernetes.io/master=:NoSchedule --overwrite", ignore_errors=True)

    # ✅ Patch and apply the ScaledJob
    print("✏️ Patching ScaledJob with optimal nodeAffinity...")
    run_command("python3 patch_scaledjob.py")

    print("📦 Applying patched KEDA ScaledJob...")
    run_command("kubectl delete scaledjob posture-analyzer-scaledjob", ignore_errors=True)
    run_command("kubectl apply -f patched-job.yaml")
    
    gpu_watcher = subprocess.Popen(["python3", "gpu_affinity_watcher.py"])

    # Launch CPU monitor and ESC listener
    cpu_monitor = subprocess.Popen(["python3", "cpu_monitor_and_offload.py"])
    esc_listener = subprocess.Popen(["python3", "stop.py"])

    try:
        while True:
            if cpu_monitor.poll() is not None or esc_listener.poll() is not None:
                print("🛑 One of the processes has exited.")
                break
            time.sleep(1)

    except KeyboardInterrupt:
        print("🔴 Interrupted. Terminating both processes...")
        cpu_monitor.terminate()
        esc_listener.terminate()
