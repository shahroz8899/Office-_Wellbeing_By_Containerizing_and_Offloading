import subprocess
import time

def get_underloaded_workers(threshold=60):
    try:
        label_output = subprocess.check_output(
            "kubectl get nodes -l role=worker --no-headers", shell=True
        ).decode()
        worker_nodes = [line.split()[0] for line in label_output.strip().splitlines() if line]

        usage_output = subprocess.check_output(
            "kubectl top nodes --no-headers", shell=True
        ).decode()
        usage_data = {
            parts[0]: int(parts[2].rstrip('%'))
            for parts in (line.split() for line in usage_output.strip().splitlines())
        }

        return [n for n in worker_nodes if usage_data.get(n, 100) < threshold]
    except Exception as e:
        print(f"⚠️ Failed to get worker usage: {e}")
        return []

def get_cpu_usage(node_name):
    try:
        output = subprocess.check_output("kubectl top nodes --no-headers", shell=True).decode()
        for line in output.strip().splitlines():
            parts = line.split()
            if parts[0] == node_name:
                return int(parts[2].rstrip('%'))
    except Exception as e:
        print(f"⚠️ Could not read CPU for {node_name}: {e}")
    return 100  # Default to overloaded

def launch_job_on_node(node_name):
    job_name = f"posture-analyzer-{int(time.time())}"
    print(f"🚀 Launching job {job_name} on {node_name}")

    with open("posture-job.yaml") as f:
        template = f.read()

    patched = (
        template
        .replace("name: posture-analyzer", f"name: {job_name}")
        .replace(
            "restartPolicy: Never",
            f"restartPolicy: Never\n      nodeName: {node_name}"
        )
    )

    with open("patched-job.yaml", "w") as f:
        f.write(patched)

    subprocess.run("kubectl apply -f patched-job.yaml", shell=True)


# 🌐 Scheduler loop
current_node = None
job_launched = False

while True:
    if current_node is None:
        # Pick a new underloaded node
        underloaded = get_underloaded_workers()
        if underloaded:
            current_node = underloaded[0]
            launch_job_on_node(current_node)
            job_launched = True
        else:
            print("⚠️ No underloaded node found. Retrying...")
    else:
        usage = get_cpu_usage(current_node)
        if usage >= 60:
            print(f"⚠️ Node {current_node} is now overloaded ({usage}%). Releasing...")
            current_node = None
            job_launched = False
        elif not job_launched:
            launch_job_on_node(current_node)
            job_launched = True
        else:
            print(f"✅ Waiting… Node {current_node} still under {usage}%. No new job launched.")

    time.sleep(1)

