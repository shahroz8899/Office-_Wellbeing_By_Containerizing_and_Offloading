from prometheus_api_client import PrometheusConnect
from typing import Dict
import urllib3
from kubernetes import client, config

# Optional: disable SSL warning if using self-signed Prometheus
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROMETHEUS_URL = "http://localhost:9090"  # Change if needed
THRESHOLD = 90  # percent

def get_node_cpu_usage() -> Dict[str, float]:
    prom = PrometheusConnect(url=PROMETHEUS_URL, disable_ssl=True)

    query = 'avg(rate(node_cpu_seconds_total{mode="idle"}[10s])) by (instance)'
    results = prom.custom_query(query)

    usage_by_node = {}

    for item in results:
        instance = item["metric"]["instance"]  # e.g., "192.168.1.135:9100"
        idle_ratio = float(item["value"][1])
        usage_percent = round((1.0 - idle_ratio) * 100, 2)
        usage_by_node[instance] = usage_percent

    return usage_by_node

def get_schedulable_ip_to_node_map() -> Dict[str, str]:
    config.load_kube_config()
    v1 = client.CoreV1Api()
    nodes = v1.list_node().items

    ip_to_node = {}

    for node in nodes:
        node_name = node.metadata.name
        taints = node.spec.taints or []
        is_tainted = any(t.effect == "NoSchedule" for t in taints)

        if not is_tainted:
            # Find InternalIP
            for addr in node.status.addresses:
                if addr.type == "InternalIP":
                    ip_to_node[addr.address] = node_name

    return ip_to_node

def get_underloaded_nodes(threshold: float = THRESHOLD) -> Dict[str, float]:
    usage_by_node = get_node_cpu_usage()
    ip_to_node = get_schedulable_ip_to_node_map()

    underloaded = {
        ip: usage
        for ip, usage in usage_by_node.items()
        if usage < threshold and strip_port(ip) in ip_to_node
    }

    sorted_nodes = dict(sorted(underloaded.items(), key=lambda x: x[1]))
    return sorted_nodes, ip_to_node

def strip_port(address: str) -> str:
    return address.split(":")[0]

if __name__ == "__main__":
    underloaded_nodes, ip_to_node = get_underloaded_nodes()
    for ip, usage in underloaded_nodes.items():
        node_name = ip_to_node[strip_port(ip)]
        print(f"{node_name} ({ip}) → {usage}% CPU used")

