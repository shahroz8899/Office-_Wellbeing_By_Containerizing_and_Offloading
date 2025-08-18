import subprocess
import time
import requests
from urllib.parse import quote
import grpc
from concurrent import futures
import externalscaler_pb2
import externalscaler_pb2_grpc

PROMETHEUS_URL = "http://localhost:9090"
QUERY_ENDPOINT = "/api/v1/query"

# GPU metric configuration per worker node
GPU_QUERIES = {
    "agx-desktop": {
        "instance": "192.168.1.135:9100",
        "metric": "jetson_gpu_usage_percent"
    },
    "orin-desktop": {
        "instance": "192.168.1.118:9100",
        "metric": "jetson_orin_gpu_load_percent"
    }
}

GPU_THRESHOLD = 20

def query_prometheus(metric_name, instance):
    query = f'{metric_name}{{instance="{instance}"}}'
    encoded_query = quote(query)
    url = f"{PROMETHEUS_URL}{QUERY_ENDPOINT}?query={encoded_query}"
    print(f"🔍 Querying Prometheus: {url}")
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        results = data.get("data", {}).get("result", [])
        if results:
            value = float(results[0]["value"][1])
            return value
    except Exception as e:
        print(f"❌ Error querying Prometheus for {instance}: {e}")
    return None

def get_available_worker_with_max_gpu():
    underloaded = []
    for node, config in GPU_QUERIES.items():
        usage = query_prometheus(config["metric"], config["instance"])
        if usage is not None:
            print(f"🔎 {node} GPU usage: {usage:.2f}%")
            if usage < GPU_THRESHOLD:
                underloaded.append((node, usage))
        else:
            print(f"⚠️ Unable to fetch GPU for {node}")
    if not underloaded:
        return None
    return sorted(underloaded, key=lambda x: x[1])[0][0]  # least used GPU

def launch_job_on_node(node_name):
    print(f"🚀 Patching all posture jobs to run on `{node_name}`...")

    subprocess.run(f"python3 patch_scaledjob.py", shell=True)

    print("📦 Applying patched posture-analyzer jobs for pi1/pi2/pi3...")
    subprocess.run("kubectl apply -f patched-job-pi1.yaml", shell=True)
    subprocess.run("kubectl apply -f patched-job-pi2.yaml", shell=True)
    subprocess.run("kubectl apply -f patched-job-pi3.yaml", shell=True)


# ---------- gRPC Scaler Implementation ---------- #

def stop_watcher_processes():
    """Stop any running gpu_affinity_watcher.py processes."""
    print("🛑 Stopping gpu_affinity_watcher.py processes...")
    try:
        # -f matches the full command line; -9 ensures immediate stop if needed.
        subprocess.run("pkill -f gpu_affinity_watcher.py", shell=True, check=False)
    except Exception as e:
        print(f"❌ Failed to stop watcher processes: {e}")

def delete_all_scaledjob_jobs():
    """Delete Jobs created by our three ScaledJobs (before pods)."""
    print("🧼 Deleting all posture-analyzer Jobs (pi1, pi2, pi3)...")
    for sj in [
        "posture-analyzer-scaledjob-pi1",
        "posture-analyzer-scaledjob-pi2",
        "posture-analyzer-scaledjob-pi3",
    ]:
        # Select Jobs by the ScaledJob label; delete them if present
        cmd = (
            f"kubectl get jobs -l scaledjob.keda.sh/name={sj} --no-headers "
            "| awk '{print $1}' | xargs -r kubectl delete job"
        )
        try:
            subprocess.run(cmd, shell=True, check=False)
        except Exception as e:
            print(f"❌ Failed deleting jobs for {sj}: {e}")

def delete_all_scaledjob_pods():
    """Delete pods created by our three ScaledJobs."""
    print("🗑️ Deleting all running posture-analyzer pods (pi1, pi2, pi3)...")
    for sj in [
        "posture-analyzer-scaledjob-pi1",
        "posture-analyzer-scaledjob-pi2",
        "posture-analyzer-scaledjob-pi3",
    ]:
        cmd = (
            f"kubectl get pods -l scaledjob.keda.sh/name={sj} --no-headers "
            "| awk '{print $1}' | xargs -r kubectl delete pod"
        )
        try:
            subprocess.run(cmd, shell=True, check=False)
        except Exception as e:
            print(f"❌ Failed deleting pods for {sj}: {e}")

# --- scaler ---

class ExternalScalerServicer(externalscaler_pb2_grpc.ExternalScalerServicer):
    def IsActive(self, request, context):
        print("🔄 KEDA called IsActive()")

        try:
            # ACTIVE if ANY node is below threshold
            for config in GPU_QUERIES.values():
                usage = query_prometheus(config["metric"], config["instance"])
                if usage is not None and usage < GPU_THRESHOLD:
                    print("🚀 Returning Active = True")

                    # (unchanged) attempt to launch watcher each time we report Active
                    try:
                        print("🚀 Launching gpu_affinity_watcher.py from IsActive()...")
                        subprocess.Popen(["python3", "gpu_affinity_watcher.py"])
                    except Exception as e:
                        print(f"❌ Failed to launch gpu_affinity_watcher.py: {e}")

                    return externalscaler_pb2.IsActiveResponse(result=True)

        except Exception as e:
            print(f"❌ IsActive failed during GPU check: {e}")

        # INACTIVE path: stop watcher(s), delete Jobs first, then Pods
        print("❌ No capacity on any node. Taking cleanup actions...")
        stop_watcher_processes()
        delete_all_scaledjob_jobs()   # <- new: ensure Jobs are removed first
        time.sleep(0.5)               # small gap to let controller start cleanup
        delete_all_scaledjob_pods()   # then force-delete any leftover Pods
        print("❌ Returning Active = False")
        return externalscaler_pb2.IsActiveResponse(result=False)

    def GetMetricSpec(self, request, context):
        metric_name = "gpu_trigger"
        metric = externalscaler_pb2.MetricSpec(metricName=metric_name, targetSize=1)
        return externalscaler_pb2.GetMetricSpecResponse(metricSpecs=[metric])

    def GetMetrics(self, request, context):
        print("📊 KEDA called GetMetrics()")
        total = 0
        for config in GPU_QUERIES.values():
            usage = query_prometheus(config["metric"], config["instance"])
            if usage is not None:
                total += max(0, 100 - usage)  # inverse logic
        return externalscaler_pb2.GetMetricsResponse(
            metricValues=[externalscaler_pb2.MetricValue(metricName="gpu_trigger", metricValue=int(total))]
        )

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    externalscaler_pb2_grpc.add_ExternalScalerServicer_to_server(ExternalScalerServicer(), server)
    server.add_insecure_port("[::]:50051")
    print("🔁 Starting gRPC External Scaler on port 50051...")

    # Print initial GPU usage before KEDA begins calling methods
    print("\n📊 Initial GPU status of all worker nodes:")
    for node, config in GPU_QUERIES.items():
        usage = query_prometheus(config["metric"], config["instance"])
        if usage is not None:
            print(f"   • {node}: {usage:.2f}% GPU used")
        else:
            print(f"   • {node}: ❌ Unable to fetch GPU usage")

    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()

