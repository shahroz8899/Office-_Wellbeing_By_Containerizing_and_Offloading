import psutil
import subprocess
import time

THRESHOLD_HIGH = 60
THRESHOLD_LOW = 50
offloaded = False
current_worker = None

def stop_master_container():
    print("⛔ Stopping master container...")
    subprocess.run("docker-compose down", shell=True)

def start_master_container():
    print("🔁 Restarting master container...")
    subprocess.run("docker-compose up -d", shell=True)

def get_available_worker():
    try:
        # Use actual label: role=worker
        label_output = subprocess.check_output(
            "kubectl get nodes -l role=worker --no-headers",
            shell=True
        ).decode()
        lines = label_output.strip().split("\n")
        worker_nodes = [line.split()[0] for line in lines if line.strip()]

        usage_output = subprocess.check_output(
            "kubectl top nodes --no-headers",
            shell=True
        ).decode()
        usage_data = {
            line.split()[0]: int(line.split()[2].replace('%', ''))
            for line in usage_output.strip().split("\n")
            if line.strip()
        }

        for node in worker_nodes:
            if usage_data.get(node, 100) < 60:
                return node
    except Exception as e:
        print(f"⚠️ Failed to get available worker node: {e}")
    return None


def launch_job_on_worker(worker_name):
    print(f"🚀 Launching job on worker: {worker_name}")
    
    # Delete old job
    subprocess.run("kubectl delete job posture-analyzer --ignore-not-found", shell=True)
    
    # Generate a patched YAML on the fly with correct nodeName
    with open("posture-job.yaml", "r") as f:
        job_yaml = f.read()
    
    patched_yaml = job_yaml.replace(
        "restartPolicy: Never",
        f"restartPolicy: Never\n      nodeName: {worker_name}"
    )
    
    # Write it to a temporary file
    with open("patched-job.yaml", "w") as f:
        f.write(patched_yaml)

    # Apply it
    subprocess.run("kubectl apply -f patched-job.yaml", shell=True)

def delete_worker_job():
    print("🛑 Deleting job from worker...")
    subprocess.run("kubectl delete job posture-analyzer", shell=True)

while True:
    cpu = psutil.cpu_percent(interval=3)
    print(f"CPU Usage: {cpu}%")

    if cpu >= THRESHOLD_HIGH and not offloaded:
        stop_master_container()
        available_worker = get_available_worker()
        if available_worker:
            launch_job_on_worker(available_worker)
            current_worker = available_worker
            offloaded = True
        else:
            print("⚠️ No available worker node found. Skipping offload.")

    elif cpu < THRESHOLD_LOW and offloaded:
        delete_worker_job()
        start_master_container()
        offloaded = False
        current_worker = None

    time.sleep(5)
