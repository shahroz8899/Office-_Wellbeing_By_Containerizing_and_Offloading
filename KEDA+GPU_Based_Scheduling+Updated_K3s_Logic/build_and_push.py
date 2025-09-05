# build_and_push.py
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

    print("🧹 Removing old Docker images for pi1/pi2/pi3...")
    IMAGES = [
        ("pi1", "Images_From_Pi1.py"),
        ("pi1-1", "Images_From_Pi1-1.py"),
        ("pi1-2", "Images_From_Pi1-2.py"),
        ("pi1-3", "Images_From_Pi1-3.py"),
        ("pi1-4", "Images_From_Pi1-4.py"),
        ("pi2", "Images_From_Pi2.py"),
        ("pi2-1", "Images_From_Pi2-1.py"),
        ("pi2-2", "Images_From_Pi2-2.py"),
        ("pi2-3", "Images_From_Pi2-3.py"),
        ("pi2-4", "Images_From_Pi2-4.py"),
        ("pi3", "Images_From_Pi3.py"),
    ]
    for tag, _ in IMAGES:
        run_command(f"docker rmi shahroz90/posture-analyzer-{tag}:latest", ignore_errors=True)

    print("🔨 Building multi-architecture Docker images and pushing to Docker Hub...")
    for tag, app in IMAGES:
        run_command(
            "docker buildx build "
            "--platform linux/amd64,linux/arm64 "
            f"--build-arg APP={app} "
            f"-t shahroz90/posture-analyzer-{tag}:latest "
            "--push ."
        )

    print("✅ Docker setup complete.")
    print("🛡️ Tainting master node (nuc) to repel posture jobs...")
    run_command("kubectl taint nodes nuc node-role.kubernetes.io/master=:NoSchedule --overwrite", ignore_errors=True)

    # ⬇️ Run the NEW even-spread patcher
    run_command("python3 patch_scaledjob.py")

    # Apply all patched ScaledJobs
    run_command("kubectl apply -f patched-job-pi1.yaml")
    run_command("kubectl apply -f patched-job-pi1-1.yaml")
    run_command("kubectl apply -f patched-job-pi1-2.yaml")
    run_command("kubectl apply -f patched-job-pi1-3.yaml")
    run_command("kubectl apply -f patched-job-pi1-4.yaml")
    run_command("kubectl apply -f patched-job-pi2.yaml")
    run_command("kubectl apply -f patched-job-pi2-1.yaml")
    run_command("kubectl apply -f patched-job-pi2-2.yaml")
    run_command("kubectl apply -f patched-job-pi2-3.yaml")
    run_command("kubectl apply -f patched-job-pi2-4.yaml")
    run_command("kubectl apply -f patched-job-pi3.yaml")

    # Start external scaler + stop helper
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
