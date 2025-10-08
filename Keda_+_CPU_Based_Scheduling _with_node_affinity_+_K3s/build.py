import subprocess
import os

RBAC_FILE = "cpu-scheduler-rbac.yaml"
JOBS_FILE = "posture-jobs.yaml"
SCHEDULER_SCRIPT = "cpu_scheduler.py"

def run(cmd, ignore_errors=False):
    print(f"👉 Running: {cmd}")
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        if ignore_errors:
            print(f"⚠️ Ignored error: {e}")
        else:
            raise

def main():
    # 0) Optional: clean up local docker bits (same as before)
    print("🔄 Stopping and removing any running container...")
    run("docker-compose down", ignore_errors=True)
    run("docker rm -f posture-analyzer", ignore_errors=True)

    print("🧹 Removing old Docker images for posture scripts...")
    for i in range(10):
        tag = "shahroz90/posture-analyzer-images_from_pi1"
        if i > 0:
            tag += f"_{i}"
        run(f"docker rmi {tag}:latest", ignore_errors=True)

    # 1) Build & push all analyzer images (unchanged)
    print("🔨 Building multi-architecture Docker images for posture analyzers...")
    for i in range(10):
        app = "Images_From_Pi1"
        if i > 0:
            app += f"_{i}"
        image_tag = f"shahroz90/posture-analyzer-{app.lower()}:latest"
        run(f"docker buildx build --platform linux/amd64,linux/arm64 "
            f"--build-arg APP={app}.py -t {image_tag} --push .")

    # 2) Apply RBAC for the custom scheduler
    print("🛡️  Applying RBAC for cpu-scheduler...")
    run(f"kubectl apply -f {RBAC_FILE}")

    # 3) Deploy Jobs
    print("🚀 Deploying posture jobs to Kubernetes...")
    run(f"kubectl apply -f {JOBS_FILE}")

    # 4) Start the custom CPU-aware scheduler (foreground)
    print("🧠 Starting custom CPU-aware scheduler...")
    run(f"python3 {SCHEDULER_SCRIPT}")

    print("✅ Done.")

if __name__ == "__main__":
    main()
