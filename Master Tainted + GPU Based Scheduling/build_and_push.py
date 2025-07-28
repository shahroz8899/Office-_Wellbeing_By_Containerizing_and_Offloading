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

   # print("▶️ Starting container with docker-compose...")
   # run_command("docker-compose up -d")

    print("✅ Docker setup complete.")

    print("📡 Launching CPU monitor and ESC listener in parallel...")
    
    print("🛡️ Tainting master node (nuc) to repel posture jobs...")
    run_command("kubectl taint nodes nuc node-role.kubernetes.io/master=:NoSchedule --overwrite", ignore_errors=True)

    # Start cpu_monitor_and_offload.py
    cpu_monitor = subprocess.Popen(["python3", "cpu_monitor_and_offload.py"])

    # Start stop_on_esc.py
    esc_listener = subprocess.Popen(["python3", "stop.py"])

    try:
        # Wait for either process to exit
        while True:
            if cpu_monitor.poll() is not None or esc_listener.poll() is not None:
                print("🛑 One of the processes has exited.")
                break
            time.sleep(1)

    except KeyboardInterrupt:
        print("🔴 Interrupted. Terminating both processes...")
        cpu_monitor.terminate()
        esc_listener.terminate()
