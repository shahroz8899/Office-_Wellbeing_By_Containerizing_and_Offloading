import subprocess

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

    print("🧹 Removing old Docker image...")
    run_command("docker rmi shahroz90/posture-analyzer", ignore_errors=True)

    print("🔨 Building multi-architecture Docker image and pushing to Docker Hub...")
    run_command("docker buildx build --platform linux/amd64,linux/arm64 -t shahroz90/posture-analyzer:latest --push .")

    print("▶️ Starting container with docker-compose...")
    run_command("docker-compose up -d")

    print("✅ Docker setup complete. Launching CPU monitor for offloading...")

    # Launch the CPU monitor script
    try:
        subprocess.run("python3 cpu_monitor_and_offload.py", shell=True)
    except Exception as e:
        print(f"❌ Failed to run CPU monitor: {e}")
