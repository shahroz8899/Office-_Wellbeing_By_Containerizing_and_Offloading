import csv, requests
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

# --- CONFIG ---
PROM_URL = "http://localhost:9090"  # <-- set this
STEP = "15s"  # match your scrape interval: 15s/30s/1m etc.

INSTANCES = [
    "192.168.1.135:9100",
    "192.168.1.35:9100",
    "192.168.1.193:9100",
    "192.168.1.42:9100",
    "192.168.1.77:9100",
    "192.168.1.118:9100",
]

# % CPU used from node_exporter (idle -> used)
QUERY_TPL = '(100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle",instance="%s"}[5m])) * 100))'
# --- END CONFIG ---

def today_epoch_range_utc():
    tz = ZoneInfo("Europe/Helsinki")
    today = datetime.now(tz).date()
    start_local = datetime.combine(today, time(10, 24, 0), tzinfo=tz)
    end_local   = datetime.combine(today, time(10, 32, 0), tzinfo=tz)
    start_utc = int(start_local.astimezone(timezone.utc).timestamp())
    end_utc   = int(end_local.astimezone(timezone.utc).timestamp())
    return start_utc, end_utc

def fetch_series(session, instance, start, end):
    q = QUERY_TPL % instance
    r = session.get(
        f"{PROM_URL}/api/v1/query_range",
        params={"query": q, "start": start, "end": end, "step": STEP},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    res = data.get("data", {}).get("result", [])
    return res[0]["values"] if res else []

def write_csv(instance, values):
    fn = f'cpu_{instance.replace(":", "_")}.csv'
    with open(fn, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_unix", "timestamp_iso_utc", "cpu_percent"])
        for ts, val in values:
            ts = int(float(ts))
            iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            try:
                v = float(val)
            except ValueError:
                v = float("nan")
            w.writerow([ts, iso, v])
    print(f"Wrote {fn}")

def main():
    start, end = today_epoch_range_utc()
    print(f"Querying UTC window {start}–{end}")
    with requests.Session() as s:
        for inst in INSTANCES:
            vals = fetch_series(s, inst, start, end)
            write_csv(inst, vals)

if __name__ == "__main__":
    main()
