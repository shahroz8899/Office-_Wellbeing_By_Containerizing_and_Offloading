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

GPU_THRESHOLD = 100

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
    job_name = f"posture-analyzer-{int(time.time())}"
    print(f"🚀 Launching job {job_name} on {node_name}")
    
    with open("posture-job.yaml", "r") as f:
        template = f.read()

    patched = (
        template
        .replace("name: posture-analyzer-scaledjob", f"name: {job_name}")
        .replace(
            "restartPolicy: Never",
            f"""restartPolicy: Never
        affinity:
          nodeAffinity:
            requiredDuringSchedulingIgnoredDuringExecution:
              nodeSelectorTerms:
              - matchExpressions:
                - key: gpu-node
                  operator: In
                  values:
                  - {node_name}"""
        )
    )

    with open("patched-job.yaml", "w") as f:
        f.write(patched)

    subprocess.run("kubectl apply -f patched-job.yaml", shell=True)

# ---------- gRPC Scaler Implementation ---------- #
class ExternalScalerServicer(externalscaler_pb2_grpc.ExternalScalerServicer):
    def IsActive(self, request, context):
        print("🔄 KEDA called IsActive()")
        for config in GPU_QUERIES.values():
            usage = query_prometheus(config["metric"], config["instance"])
            if usage is not None and usage < GPU_THRESHOLD:
                print("🚀 Returning Active = True")
                return externalscaler_pb2.IsActiveResponse(result=True)
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

    # ✅ NEW: print initial GPU usage before KEDA begins calling methods
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