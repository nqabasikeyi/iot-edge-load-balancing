import requests
import time
import pandas as pd

NODES = [
    "node1:5001",
    "node2:5002",
    "node3:5003",
    "node4:5004"
]

CPU_THRESHOLD = 75
LOG_FILE = "monitor_log.csv"

def get_node_metrics(node):
    try:
        r = requests.get(f"http://{node}/health", timeout=2)
        return r.json()
    except:
        return None

def select_lowest_loaded(nodes_metrics):
    return min(nodes_metrics, key=lambda x: x["cpu_percent"])

def monitor_loop():
    logs = []
    while True:
        metrics = []
        for node in NODES:
            data = get_node_metrics(node)
            if data:
                data["address"] = node
                metrics.append(data)

        for node_data in metrics:
            if node_data["cpu_percent"] > CPU_THRESHOLD:
                target = select_lowest_loaded(metrics)
                if target["address"] != node_data["address"]:
                    print(f"Offloading from {node_data['address']} to {target['address']}")

        logs.extend(metrics)
        df = pd.DataFrame(logs)
        df.to_csv(LOG_FILE, index=False)

        time.sleep(5)

if __name__ == "__main__":
    monitor_loop()