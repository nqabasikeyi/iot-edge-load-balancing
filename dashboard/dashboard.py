from flask import Flask, render_template, jsonify, request
import requests
import time
import threading

app = Flask(__name__)

NODES = [
    "node1:5001",
    "node2:5002",
    "node3:5003",
    "node4:5004"
]

OVERLOAD_THRESHOLD = 80
REDISTRIBUTION_DELAY = 5

# Prevent multiple redistribution threads per node
redistribution_lock = {node: False for node in NODES}


# -----------------------------------
# Dashboard Page
# -----------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# -----------------------------------
# Fetch Node Data + Detect Overload
# -----------------------------------
@app.route("/nodes")
def get_nodes():
    data = []

    total_cpu = 0
    total_queue = 0
    active_nodes = 0
    overloaded_nodes = 0

    for node in NODES:
        try:
            start = time.time()
            r = requests.get(f"http://{node}/health", timeout=2)
            latency = (time.time() - start) * 1000

            node_data = r.json()
            node_data["address"] = node

            # If node reports offline → force latency 0
            if node_data.get("status") == "offline":
                node_data["latency_ms"] = 0
                node_data["overloaded"] = False
                node_data["load_score"] = 0
            else:
                node_data["latency_ms"] = round(latency, 2)

                motion = node_data.get("sensor_values", {}).get("motion", 0)
                cpu = node_data.get("cpu_percent", 0)
                queue = node_data.get("queue_length", 0)

                load_score = (cpu * 0.6) + (queue * 10 * 0.3) + (motion * 0.1)
                node_data["load_score"] = round(load_score, 2)

                if load_score > OVERLOAD_THRESHOLD:
                    node_data["overloaded"] = True
                    overloaded_nodes += 1

                    # Prevent thread spam
                    if not redistribution_lock[node]:
                        redistribution_lock[node] = True
                        threading.Thread(
                            target=delayed_redistribute,
                            args=(node,),
                            daemon=True
                        ).start()
                else:
                    node_data["overloaded"] = False
                    redistribution_lock[node] = False

                total_cpu += cpu
                total_queue += queue
                active_nodes += 1

            data.append(node_data)

        except:
            data.append({
                "node": node,
                "address": node,
                "status": "offline",
                "cpu_percent": 0,
                "memory_percent": 0,
                "queue_length": 0,
                "latency_ms": 0,
                "load_score": 0,
                "overloaded": False
            })

    system_summary = {
        "average_cpu": round(total_cpu / active_nodes, 2) if active_nodes else 0,
        "total_queue": total_queue,
        "active_nodes": active_nodes,
        "overloaded_nodes": overloaded_nodes
    }

    return jsonify({
        "nodes": data,
        "system": system_summary
    })


# -----------------------------------
# Delayed Load Redistribution
# -----------------------------------
def delayed_redistribute(overloaded_node):
    time.sleep(REDISTRIBUTION_DELAY)

    try:
        for node in NODES:
            if node != overloaded_node:
                r = requests.get(f"http://{node}/health", timeout=2)
                data = r.json()

                if data.get("status") == "active" and data.get("cpu_percent", 0) < 50:
                    requests.post(
                        f"http://{overloaded_node}/migrate",
                        json={"target": node, "data": {"task": "redistributed"}},
                        timeout=2
                    )
                    break
    except:
        pass

    redistribution_lock[overloaded_node] = False


# -----------------------------------
# Motion Control
# -----------------------------------
@app.route("/control_people", methods=["POST"])
def control_people():
    payload = request.json
    node = payload["node"]
    people = payload["people"]

    try:
        requests.post(f"http://{node}/set_people",
                      json={"people": people},
                      timeout=2)
        return jsonify({"status": "success"})
    except:
        return jsonify({"error": "Node unreachable"}), 500


# -----------------------------------
# Sensor Control
# -----------------------------------
@app.route("/control_sensor", methods=["POST"])
def control_sensor():
    payload = request.json
    node = payload["node"]
    sensor = payload["sensor"]
    action = payload["action"]

    try:
        requests.post(f"http://{node}{action}", json={"sensor": sensor}, timeout=2)
        return jsonify({"status": "updated"})
    except:
        return jsonify({"error": "Node unreachable"}), 500


# -----------------------------------
# Node Control
# -----------------------------------
@app.route("/control_node", methods=["POST"])
def control_node():
    payload = request.json
    node = payload["node"]
    action = payload["action"]

    endpoint = "/shutdown_node" if action == "shutdown" else "/activate_node"

    try:
        requests.post(f"http://{node}{endpoint}", timeout=2)
        return jsonify({"status": action})
    except:
        return jsonify({"error": "Node unreachable"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7000)