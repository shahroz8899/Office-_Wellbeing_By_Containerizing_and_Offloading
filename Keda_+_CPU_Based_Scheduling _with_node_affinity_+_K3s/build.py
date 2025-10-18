#!/usr/bin/env python3
import json, os, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

REGISTRY_USER   = os.getenv("REGISTRY_USER", "shahroz90").strip()
NAMESPACE       = os.getenv("NAMESPACE", "posture").strip()
PROM_URL        = os.getenv("PROM_URL", "http://localhost:9090").strip()
CPU_THRESHOLD   = os.getenv("CPU_THRESHOLD", "0.70").strip()
EXCLUDE_NODES   = os.getenv("EXCLUDE_NODES", "localhost").strip()
GRPC_PORT       = os.getenv("GRPC_PORT", "8080").strip()
HTTP_PORT       = os.getenv("HTTP_PORT", "8088").strip()
JOB_SELECTOR    = os.getenv("JOB_SELECTOR", "app=posture-queued").strip()
ALLOWED_URL     = os.getenv("ALLOWED_URL", f"http://localhost:{HTTP_PORT}/allowed").strip()
DOCKER_PLATFORM = os.getenv("DOCKER_PLATFORM", "linux/arm64/v8").strip()

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

ROOT = Path(__file__).resolve().parent
LOGDIR = ROOT / "_logs"
PIDFILE = ROOT / "_pids.json"
JOBS_FILE = ROOT / "jobs-queue.yaml"
PY = sys.executable

def step(title):
    print(f"\n{title}")
    print("—" * len(title))

def run(cmd, check=True, env=None):
    print(f"› {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, env=env)

def run_bg(cmd, log_path: Path, env=None):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(log_path, "ab", buffering=0)
    print(f"▶ {' '.join(cmd)}  (logs: {log_path})")
    return subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, cwd=str(ROOT))

def ensure_cli(name):
    if not shutil.which(name):
        print(f"ERROR: '{name}' not found in PATH.")
        sys.exit(1)

def main():
    ensure_cli("kubectl"); ensure_cli("docker")

    # 1) Cleanup
    step("🧹 Cleaning Kubernetes resources & old analyzer images")
    run(["kubectl", "get", "ns", NAMESPACE], check=False)

    # Delete Deployments (if any)
    run(["kubectl", "-n", NAMESPACE, "delete", "deploy",
         "posture-external-scaler", "posture-controller",
         "--ignore-not-found", "--wait=false"], check=False)

    # Delete Services that might be left over
    run(["kubectl", "-n", NAMESPACE, "delete", "svc",
         "posture-external-scaler", "posture-controller",
         "--ignore-not-found"], check=False)

    # Delete Jobs and Pods quickly / non-blocking
    run(["kubectl", "-n", NAMESPACE, "delete", "job", "--all", "--wait=false"], check=False)
    run(["kubectl", "-n", NAMESPACE, "delete", "pod", "--all",
         "--force", "--grace-period=0", "--wait=false"], check=False)

    # Optional prune docker images
    run(["docker", "image", "prune", "-f"], check=False)
    try:
        out = subprocess.check_output(
            ["bash", "-lc", f"docker images '{REGISTRY_USER}/posture-analyzer-pi1-*' -q | uniq"],
            text=True).strip()
        if out:
            run(["bash", "-lc", f"docker rmi -f {out}"], check=False)
    except Exception:
        pass

    # 2) Namespace
    step("🧰 Ensuring namespace")
    if run(["kubectl", "get", "ns", NAMESPACE], check=False).returncode != 0:
        run(["kubectl", "create", "ns", NAMESPACE])

    # 3) buildx
    step("🧱 Ensuring docker buildx builder…")
    run(["bash", "-lc", "docker buildx inspect posturebuilder >/dev/null 2>&1 || docker buildx create --name posturebuilder --use"], check=False)
    run(["docker", "buildx", "use", "posturebuilder"], check=False)
    run(["bash", "-lc", "docker run --privileged --rm tonistiigi/binfmt --install all >/dev/null 2>&1 || true"], check=False)

    # 4) Build analyzers
    step("🔨 Building analyzer images")
    for i, script in enumerate(ANALYZER_SCRIPTS):
        image = f"{REGISTRY_USER}/posture-analyzer-pi1-{i}:latest"
        print(f"📦 {image}  ←  {script}")
        run([
            "docker", "buildx", "build",
            "--platform", DOCKER_PLATFORM,
            "-f", "Dockerfile",
            "--build-arg", f"APP={script}",
            "-t", image,
            "--push",
            "."
        ])

    print("✅ Analyzer images built & pushed.")

    # 5) Apply Jobs
    step("📜 Applying queued Jobs from jobs-queue.yaml")
    if not JOBS_FILE.exists():
        print(f"ERROR: {JOBS_FILE} not found.")
        sys.exit(1)
    run(["kubectl", "apply", "-n", NAMESPACE, "-f", str(JOBS_FILE)])
    print("\n✅ Boot sequence complete:\n   • 10 Jobs created with spec.suspend=true (queued)")

    # 6) Start local processes
    step("▶ Starting local processes (external_scaler, controller, queue_releaser)")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    scaler_env = {**os.environ, "EXCLUDE_NODES": EXCLUDE_NODES, "PROM_URL": PROM_URL,
                  "CPU_THRESHOLD": CPU_THRESHOLD, "GRPC_PORT": GRPC_PORT, "HTTP_PORT": HTTP_PORT}
    ctrl_env   = {**os.environ, "EXCLUDE_NODES": EXCLUDE_NODES, "PROM_URL": PROM_URL,
                  "CPU_THRESHOLD": CPU_THRESHOLD, "CONTROLLER_PORT": "8090"}
    rel_env    = {**os.environ, "NAMESPACE": NAMESPACE, "JOB_SELECTOR": JOB_SELECTOR,
                  "ALLOWED_URL": ALLOWED_URL, "POLL_SECONDS": "5"}

    p_scaler = run_bg([PY, "external_scaler.py"], LOGDIR / f"external_scaler_{ts}.log", env=scaler_env)
    p_ctrl   = run_bg([PY, "controller.py"],      LOGDIR / f"controller_{ts}.log",      env=ctrl_env)
    p_rel    = run_bg([PY, "queue_releaser.py"],  LOGDIR / f"queue_releaser_{ts}.log",  env=rel_env)

    pids = {
        "external_scaler.py": p_scaler.pid,
        "controller.py": p_ctrl.pid,
        "queue_releaser.py": p_rel.pid,
        "logs_dir": str(LOGDIR),
        "started_at": ts,
        "config": {
            "namespace": NAMESPACE, "prom_url": PROM_URL, "cpu_threshold": CPU_THRESHOLD,
            "exclude_nodes": EXCLUDE_NODES, "grpc_port": GRPC_PORT, "http_port": HTTP_PORT,
            "allowed_url": ALLOWED_URL,
        },
    }
    PIDFILE.write_text(json.dumps(pids, indent=2))
    print(f"📝 PIDs written to {PIDFILE}")

    step("ℹ️ Quick status commands")
    print(f"curl -s http://localhost:{HTTP_PORT}/allowed | jq")
    print(f"kubectl -n {NAMESPACE} get nodes --show-labels | grep posture || true")
    print(f"kubectl -n {NAMESPACE} get jobs -o wide")
    print(f"kubectl -n {NAMESPACE} get pods -w")
    print("\n🎯 Done. Processes are running in background; logs in ./_logs.")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\nERROR (exit {e.returncode}): {' '.join(e.cmd) if isinstance(e.cmd, list) else e.cmd}")
        sys.exit(e.returncode)
