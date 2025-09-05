# cpu_monitor_and_offload.py
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

GPU_QUERIES = {
    "agx-desktop": {"instance": "192.168.1.135:9100", "metric": "jetson_gpu_usage_percent"},
    "orin-desktop": {"instance": "192.168.1.118:9100", "metric": "jetson_orin_gpu_load_percent"},
    "orin1-desktop": {"instance": "192.168.1.77:9100", "metric": "jetson_orin1_gpu_usage_percent"},
    "orin2-desktop": {"instance": "192.168.1.35:9100", "metric": "jetson_orin2_gpu_usage_percent"},
    "orin3-desktop": {"instance": "192.168.1.XX:9100", "metric": "jetson_orin3_gpu_usage_percent"},
    "nano1-desktop": {"instance": "192.168.1.193:9100", "metric": "jetson_nano1_gpu_usage_percent"},
    "nano2-desktop": {"instance": "192.168.1.42:9100", "metric": "jetson_nano2_gpu_usage_percent"},
}

GPU_THRESHOLD = 90  # configurable if you like

def query_prometheus(metric_name, instance):
    query = f'{metric_name}{{instance="{instance}"}}'
    url = f"{PROMETHEUS_URL}{QUERY_ENDPOINT}?query={quote(query)}"
    print(f"🔍 Querying Prometheus: {url}")
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        res = data.get("data", {}).get("result", [])
        if res:
            return float(res[0]["value"][1])
    except Exception as e:
        print(f"❌ Error querying {instance}: {e}")
    return None

def stop_balancer():
    print("🛑 Stopping gpu_balancer.py processes...")
    subprocess.run("pkill -f gpu_balancer.py", shell=True, check=False)

def delete_all_scaledjob_jobs():
    print("🧼 Deleting all posture-analyzer Jobs...")
    for sj in [
        "posture-analyzer-scaledjob-pi1",
        "posture-analyzer-scaledjob-pi1-1",
        "posture-analyzer-scaledjob-pi1-2",
        "posture-analyzer-scaledjob-pi1-3",
        "posture-analyzer-scaledjob-pi1-4",
        "posture-analyzer-scaledjob-pi2",
        "posture-analyzer-scaledjob-pi2-1",
        "posture-analyzer-scaledjob-pi2-2",
        "posture-analyzer-scaledjob-pi2-3",
        "posture-analyzer-scaledjob-pi2-4",
        "posture-analyzer-scaledjob-pi3",
    ]:
        cmd = f"kubectl get jobs -l scaledjob.keda.sh/name={sj} --no-headers | awk '{{print $1}}' | xargs -r kubectl delete job"
        subprocess.run(cmd, shell=True, check=False)

def delete_all_scaledjob_pods():
    print("🗑️ Deleting leftover posture-analyzer Pods...")
    for sj in [
        "posture-analyzer-scaledjob-pi1",
        "posture-analyzer-scaledjob-pi1-1",
        "posture-analyzer-scaledjob-pi1-2",
        "posture-analyzer-scaledjob-pi1-3",
        "posture-analyzer-scaledjob-pi1-4",
        "posture-analyzer-scaledjob-pi2",
        "posture-analyzer-scaledjob-pi2-1",
        "posture-analyzer-scaledjob-pi2-2",
        "posture-analyzer-scaledjob-pi2-3",
        "posture-analyzer-scaledjob-pi2-4",
        "posture-analyzer-scaledjob-pi3",
    ]:
        cmd = f"kubectl get pods -l scaledjob.keda.sh/name={sj} --no-headers | awk '{{print $1}}' | xargs -r kubectl delete pod"
        subprocess.run(cmd, shell=True, check=False)

class ExternalScalerServicer(externalscaler_pb2_grpc.ExternalScalerServicer):
    def IsActive(self, request, context):
        print("🔄 KEDA called IsActive()")
        try:
            for cfg in GPU_QUERIES.values():
                usage = query_prometheus(cfg["metric"], cfg["instance"])
                if usage is not None and usage < GPU_THRESHOLD:
                    print("🚀 Returning Active=True; ensuring gpu_balancer.py is running...")
                    # Start (or re-start) the balancer; let multiple calls be idempotent-ish.
                    try:
                        subprocess.Popen(["python3", "gpu_balancer.py"])
                    except Exception as e:
                        print(f"❌ Failed to launch balancer: {e}")
                    return externalscaler_pb2.IsActiveResponse(result=True)
        except Exception as e:
            print(f"❌ IsActive error: {e}")

        # INACTIVE path: stop balancer and clean up (Jobs first, then Pods)
        print("❌ No capacity on any node → stopping balancer + cleanup, returning Active=False")
        stop_balancer()
        delete_all_scaledjob_jobs()
        time.sleep(0.5)
        delete_all_scaledjob_pods()
        return externalscaler_pb2.IsActiveResponse(result=False)

    def GetMetricSpec(self, request, context):
        metric = externalscaler_pb2.MetricSpec(metricName="gpu_trigger", targetSize=1)
        return externalscaler_pb2.GetMetricSpecResponse(metricSpecs=[metric])

    def GetMetrics(self, request, context):
        print("📊 KEDA called GetMetrics()")
        total_capacity = 0
        for cfg in GPU_QUERIES.values():
            usage = query_prometheus(cfg["metric"], cfg["instance"])
            if usage is not None:
                total_capacity += max(0, 100 - usage)
        return externalscaler_pb2.GetMetricsResponse(
            metricValues=[externalscaler_pb2.MetricValue(metricName="gpu_trigger", metricValue=int(total_capacity))]
        )

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    externalscaler_pb2_grpc.add_ExternalScalerServicer_to_server(ExternalScalerServicer(), server)
    server.add_insecure_port("[::]:50051")
    print("🔁 Starting gRPC External Scaler on :50051 ...")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
