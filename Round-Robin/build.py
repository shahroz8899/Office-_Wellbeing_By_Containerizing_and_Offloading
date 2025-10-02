import subprocess
import time
import sys
import os

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

    print("🧹 Removing old Docker images for posture scripts...")
    IMAGES = [
        ("pi1", "Images_From_Pi1.py"),
        ("pi1-1", "Images_From_Pi1_1.py"),
        ("pi1-2", "Images_From_Pi1_2.py"),
        ("pi1-3", "Images_From_Pi1_3.py"),
        ("pi1-4", "Images_From_Pi1_4.py"),
        ("pi1-5", "Images_From_Pi1_5.py"),
        ("pi1-6", "Images_From_Pi1_6.py"),
        ("pi1-7", "Images_From_Pi1_7.py"),
        ("pi1-8", "Images_From_Pi1_8.py"),
        ("pi1-9", "Images_From_Pi1_9.py"),
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

    print("🔨 Building rr-scheduler image (multi-arch) and pushing to Docker Hub...")
    run_command(
        "docker buildx build "
        "--platform linux/amd64,linux/arm64 "
        "-f Dockerfile.rr "
        "-t shahroz90/rr-scheduler:latest "
        "--push ."
    )

    print("✅ Docker setup complete.")
    print("🛡️ Tainting master node (nuc) to repel posture jobs...")
    run_command("kubectl taint nodes nuc node-role.kubernetes.io/master=:NoSchedule --overwrite", ignore_errors=True)

    # ⬇️ Added here: Deploy rr-scheduler automatically
    print("🧠 Deploying rr-scheduler to cluster...")
    run_command("kubectl apply -f rr-scheduler.yaml")

    # ⬇️ Launch posture jobs
    print("🚀 Launching posture analysis jobs to trigger round-robin scheduler...")
    run_command("kubectl apply -f posture-jobs.yaml")

    # 🔚 Start stop.py to wait for user input or signal
    try:
        if sys.stdin and sys.stdin.isatty():
            esc_listener = subprocess.Popen(
                ["python3", "stop.py"],
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        else:
            tty = open("/dev/tty", "r+")
            esc_listener = subprocess.Popen(
                ["python3", "stop.py"],
                stdin=tty,
                stdout=sys.stdout,
                stderr=sys.stderr,
                close_fds=False,
            )
    except Exception:
        esc_listener = subprocess.Popen(["python3", "stop.py"])
