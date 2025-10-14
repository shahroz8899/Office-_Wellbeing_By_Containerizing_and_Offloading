import os
import subprocess
from datetime import datetime, timezone

# ---- Config ----
NAMESPACE = os.getenv("NAMESPACE", "posture")
PROM_URL = os.getenv("PROM_URL", "http://10.43.181.60:9090")
CPU_THRESHOLD = os.getenv("CPU_THRESHOLD", "0.70")
METRIC_NAME = os.getenv("METRIC_NAME", "available_node_count_30s")
CONTROLLER_URL = os.getenv(
    "CONTROLLER_URL",
    "http://posture-controller.posture.svc.cluster.local:8080/overload"
)

SCALER_IMAGE_REPO = os.getenv("SCALER_IMAGE_REPO", "shahroz90/posture-external-scaler")
SCALER_DOCKERFILE = os.getenv("SCALER_DOCKERFILE", "Dockerfile.scaler")

CONTROLLER_IMAGE_REPO = os.getenv("CONTROLLER_IMAGE_REPO", "shahroz90/posture-controller")
CONTROLLER_DOCKERFILE = os.getenv("CONTROLLER_DOCKERFILE", "Dockerfile.controller")

ANALYZER_REPO_BASE = os.getenv("ANALYZER_REPO_BASE", "shahroz90/posture-analyzer-pi1")
ANALYZER_SCRIPTS = [
    "Images_From_Pi1.py",
    "Images_From_Pi1_1.py",
    "Images_From_Pi1_2.py",
    "Images_From_Pi1_3.py",
    "Images_From_Pi1_4.py",
    "Images_From_Pi1_5.py",
    "Images_From_Pi1_6.py",
    "Images_From_Pi1_7.py",
    "Images_From_Pi1_8.py",
    "Images_From_Pi1_9.py",
]

# ✅ Jetson nodes are ARM64, NUC master is AMD64 → build multi-arch for infra
PLATFORMS_MULTIARCH = "linux/amd64,linux/arm64/v8"
PLATFORMS_ANALYZERS = "linux/arm64/v8"

# ---- Helpers ----
def sh(cmd: str, check: bool = True):
    print(f"› {cmd}")
    rc = subprocess.call(cmd, shell=True)
    if check and rc != 0:
        raise SystemExit(rc)

def ts_tag() -> str:
    return datetime.now(timezone.utc).strftime("v%Y%m%d-%H%M%S")

# ---- Cleanup ----
def cleanup_environment():
    print("🧹 Cleaning up old Kubernetes resources and Docker images...")
    sh(f"kubectl -n {NAMESPACE} delete deploy posture-external-scaler --ignore-not-found", check=False)
    sh(f"kubectl -n {NAMESPACE} delete deploy posture-controller --ignore-not-found", check=False)
    sh(f"kubectl -n {NAMESPACE} delete scaledjob --all --ignore-not-found", check=False)
    sh(f"kubectl -n {NAMESPACE} delete job --all --ignore-not-found", check=False)
    sh(f"kubectl -n {NAMESPACE} delete pod --all --ignore-not-found", check=False)
    sh(f"kubectl -n {NAMESPACE} delete svc posture-external-scaler --ignore-not-found", check=False)
    sh(f"kubectl -n {NAMESPACE} delete svc posture-controller --ignore-not-found", check=False)
    sh("docker image prune -f", check=False)
    sh(f"docker rmi $(docker images {SCALER_IMAGE_REPO} -q) -f || true", check=False)
    sh(f"docker rmi $(docker images {CONTROLLER_IMAGE_REPO} -q) -f || true", check=False)
    sh(f"docker rmi $(docker images '{ANALYZER_REPO_BASE}-*' -q) -f || true", check=False)

# ---- Main build process ----
def main():
    cleanup_environment()

    # Namespace + ConfigMap
    print("🧰 Ensuring namespace and ConfigMap...")
    sh(f"kubectl get ns {NAMESPACE} || kubectl create ns {NAMESPACE}", check=False)
    cm = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config
  namespace: {NAMESPACE}
data:
  PROM_URL: "{PROM_URL}"
"""
    sh(f"cat <<'EOF' | kubectl apply -f -\n{cm}\nEOF")

    # ---- Buildx setup ----
    print("🧱 Ensuring docker buildx builder…")
    sh("docker buildx inspect posturebuilder >/dev/null 2>&1 || docker buildx create --name posturebuilder --use", check=False)
    sh("docker buildx use posturebuilder", check=False)
    sh("docker run --privileged --rm tonistiigi/binfmt --install all >/dev/null 2>&1 || true", check=False)

    # ---- External Scaler ----
    print("🔧 Building External Scaler image (multi-arch)…")
    scaler_tag = ts_tag()
    scaler_image = f"{SCALER_IMAGE_REPO}:{scaler_tag}"
    sh(f"docker buildx build --platform {PLATFORMS_MULTIARCH} -t {scaler_image} -f {SCALER_DOCKERFILE} --push .")

    print("🚀 Deploying External Scaler (port 8080)...")
    scaler_yaml = f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: posture-external-scaler
  namespace: {NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: posture-external-scaler
  template:
    metadata:
      labels:
        app: posture-external-scaler
    spec:
      nodeSelector:
        kubernetes.io/hostname: nuc
      containers:
        - name: scaler
          image: {scaler_image}
          imagePullPolicy: Always
          ports:
            - containerPort: 8080
          env:
            - name: PROM_URL
              valueFrom:
                configMapKeyRef:
                  name: prometheus-config
                  key: PROM_URL
            - name: CPU_THRESHOLD
              value: "{CPU_THRESHOLD}"
            - name: METRIC_NAME
              value: "{METRIC_NAME}"
            - name: CONTROLLER_URL
              value: "{CONTROLLER_URL}"
---
apiVersion: v1
kind: Service
metadata:
  name: posture-external-scaler
  namespace: {NAMESPACE}
spec:
  selector:
    app: posture-external-scaler
  ports:
    - name: grpc
      port: 8080
      targetPort: 8080
"""
    sh(f"cat <<'EOF' | kubectl apply -f -\n{scaler_yaml}\nEOF")
    sh(f"kubectl -n {NAMESPACE} rollout status deploy/posture-external-scaler --timeout=180s")

    # ---- Controller ----
    print("🔧 Building Controller image (multi-arch)…")
    controller_image = f"{CONTROLLER_IMAGE_REPO}:latest"
    sh(f"docker buildx build --platform {PLATFORMS_MULTIARCH} -t {controller_image} -f {CONTROLLER_DOCKERFILE} --push .")

    print("🚀 Applying Controller manifests…")
    sh(f"kubectl apply -n {NAMESPACE} -f controller-rbac.yaml")
    sh(f"kubectl apply -n {NAMESPACE} -f controller-deployment.yaml")
    sh(f"kubectl -n {NAMESPACE} set image deploy/posture-controller controller={controller_image}", check=False)
    sh(f"kubectl -n {NAMESPACE} rollout restart deploy/posture-controller")
    sh(f"kubectl -n {NAMESPACE} rollout status deploy/posture-controller --timeout=180s")

    # ---- Analyzer images ----
    print("🔨 Building analyzer images for ARM64…")
    for i, script in enumerate(ANALYZER_SCRIPTS):
        img = f"{ANALYZER_REPO_BASE}-{i}:latest"
        print(f"📦 {img}  ←  {script}")
        sh(f"docker buildx build --platform {PLATFORMS_ANALYZERS} --build-arg APP='{script}' -t {img} --push .")
    print("✅ Analyzer images built & pushed.")

    # ---- ScaledJobs ----
    print("📜 Applying ScaledJobs (10 analyzer jobs)...")
    sh(f"kubectl apply -n {NAMESPACE} -f scaledjobs-all.yaml")

    print("✅ All components deployed successfully.")
    print("ℹ️  KEDA will now queue and release jobs based on available nodes (check `kubectl get pods -n posture -w`).")

if __name__ == "__main__":
    main()
