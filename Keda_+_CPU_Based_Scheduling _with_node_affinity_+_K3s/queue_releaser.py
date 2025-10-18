import os, time, random, requests
from typing import List
from kubernetes import client, config

NAMESPACE = os.getenv("NAMESPACE", "posture")
LABEL_SELECTOR = os.getenv("JOB_SELECTOR", "app=posture-queued")
ALLOWED_URL = os.getenv("ALLOWED_URL", "http://localhost:8088/allowed")
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "5"))

def load_kube():
    config.load_kube_config()  # running on NUC
    return client.BatchV1Api()

def is_completed(j) -> bool:
    conds = j.status.conditions or []
    return any(c.type == "Complete" and c.status == "True" for c in conds)

def is_suspended(j) -> bool:
    # Job.spec.suspend is a boolean
    return bool(j.spec.suspend)

def list_jobs(batch) -> List[client.V1Job]:
    return batch.list_namespaced_job(NAMESPACE, label_selector=LABEL_SELECTOR).items

def patch_suspend(batch, name: str, suspend: bool):
    body = {"spec": {"suspend": suspend}}
    batch.patch_namespaced_job(name, NAMESPACE, body)

def get_allowed() -> int:
    try:
        r = requests.get(ALLOWED_URL, timeout=3)
        r.raise_for_status()
        return int(r.json().get("allowed", 0))
    except Exception:
        return 0

def reconcile(batch):
    jobs = list_jobs(batch)
    running = [j for j in jobs if (not is_suspended(j)) and (not is_completed(j))]
    queued  = [j for j in jobs if is_suspended(j) and (not is_completed(j))]

    allowed = get_allowed()
    need = max(0, allowed - len(running))

    if need > 0 and queued:
        random.shuffle(queued)  # randomize release order (tie-breaks)
        to_release = queued[:need]
        for j in to_release:
            patch_suspend(batch, j.metadata.name, False)
        print(f"[releaser] allowed={allowed} running={len(running)} queued={len(queued)} -> released {len(to_release)}")
    else:
        print(f"[releaser] allowed={allowed} running={len(running)} queued={len(queued)} -> no change")

def main():
    batch = load_kube()
    while True:
        try:
            reconcile(batch)
        except Exception as e:
            print(f"[releaser] error: {e}")
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
