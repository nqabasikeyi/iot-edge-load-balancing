from flask import Flask, request, jsonify
import os
from metrics import get_metrics
from task_manager import TaskManager
import requests

app = Flask(__name__)
task_manager = TaskManager()

sensors = {
    "temperature": "active",
    "humidity": "active",
    "motion": "active"
}

node_active = True

NODE_ID = os.getenv("NODE_ID", "node")
PORT = int(os.getenv("PORT", 5000))

@app.route("/health", methods=["GET"])
def health():
    global node_active

    # If node is switched off
    if not node_active:
        return jsonify({
            "node": NODE_ID,
            "cpu_percent": 0,
            "memory_percent": 0,
            "queue_length": 0,
            "status": "offline",
            "sensors": sensors
        })

    # Normal active state
    metrics = get_metrics()
    metrics["node"] = NODE_ID
    metrics["queue_length"] = task_manager.get_queue_length()
    metrics["status"] = "active"
    metrics["sensors"] = sensors

    return jsonify(metrics)

@app.route("/task", methods=["POST"])
def create_task():
    payload = request.json
    task_id = task_manager.create_task(payload)
    return jsonify({"task_id": task_id, "node": NODE_ID})

@app.route("/status/<task_id>", methods=["GET"])
def task_status(task_id):
    return jsonify(task_manager.get_status(task_id))

@app.route("/migrate", methods=["POST"])
def migrate_task():
    payload = request.json
    target = payload["target"]
    task_data = payload["data"]

    response = requests.post(f"http://{target}/task", json=task_data)
    return jsonify(response.json())

@app.route("/fail_sensor", methods=["POST"])
def fail_sensor():
    sensor = request.json["sensor"]
    sensors[sensor] = "failed"
    return jsonify({"status": "failed", "sensor": sensor})

@app.route("/recover_sensor", methods=["POST"])
def recover_sensor():
    sensor = request.json["sensor"]
    sensors[sensor] = "active"
    return jsonify({"status": "active", "sensor": sensor})

@app.route("/shutdown_node", methods=["POST"])
def shutdown_node():
    global node_active
    node_active = False
    return jsonify({"status": "offline"})

@app.route("/activate_node", methods=["POST"])
def activate_node():
    global node_active
    node_active = True
    return jsonify({"status": "active"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)



@app.route("/fail_sensor", methods=["POST"])
def fail_sensor():
    sensor = request.json.get("sensor")
    if sensor in sensors:
        sensors[sensor] = "failed"
        return jsonify({"message": f"{sensor} failed"})
    return jsonify({"error": "Invalid sensor"}), 400


@app.route("/recover_sensor", methods=["POST"])
def recover_sensor():
    sensor = request.json.get("sensor")
    if sensor in sensors:
        sensors[sensor] = "active"
        return jsonify({"message": f"{sensor} recovered"})
    return jsonify({"error": "Invalid sensor"}), 400


@app.route("/shutdown_node", methods=["POST"])
def shutdown_node():
    global node_active
    node_active = False
    return jsonify({"message": "Node shutdown"})


@app.route("/activate_node", methods=["POST"])
def activate_node():
    global node_active
    node_active = True
    return jsonify({"message": "Node activated"})