import subprocess
import time

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
    job_name = f"posture-analyzer-{int(time.time())}"
    print(f"🚀 Launching job {job_name} on worker: {worker_name}")

    # Read the base job YAML
    with open("posture-job.yaml", "r") as f:
        job_yaml = f.read()

    # Patch job name and nodeName
    job_yaml = job_yaml.replace("name: posture-analyzer", f"name: {job_name}")
    job_yaml = job_yaml.replace(
        "restartPolicy: Never",
        f"restartPolicy: Never\n      nodeName: {worker_name}"
    )

    # Write to a temporary YAML file
    with open("patched-job.yaml", "w") as f:
        f.write(job_yaml)

    # Apply the job
    subprocess.run("kubectl apply -f patched-job.yaml", shell=True)

# Infinite loop to continuously offload
while True:
    worker = get_available_worker()
    if worker:
        launch_job_on_worker(worker)
    else:
        print("⚠️ No available worker node found. Will retry.")
    
    time.sleep(5)  # Pause to avoid spamming jobs too frequently
