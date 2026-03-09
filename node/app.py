from flask import Flask, request, jsonify
import os
import time
import random
from collections import deque

app = Flask(__name__)

# -----------------------------
# Node Identity
# -----------------------------
NODE_ID = os.getenv("NODE_ID", "node1")
NODE_ROLE = os.getenv("NODE_ROLE", "edge")
PORT = int(os.getenv("PORT", 5000))

# -----------------------------
# Node State
# -----------------------------
node_active = True

# -----------------------------
# Building Configuration
# -----------------------------
BUILDINGS = {
    "node1": {"name": "Library", "size": 280, "capacity": 80},
    "node2": {"name": "Lecturer Office", "size": 40, "capacity": 15},
    "node3": {"name": "Laboratory", "size": 160, "capacity": 50},
    "node4": {"name": "Classroom", "size": 200, "capacity": 70},
    "fog1": {"name": "Campus Fog Server", "size": 20, "capacity": 150},
}
building_info = BUILDINGS.get(NODE_ID, {"name": "Unknown", "size": 100, "capacity": 20})

# -----------------------------
# Initial Occupancy per Building
# -----------------------------
INITIAL_PEOPLE = {
    "node1": 10,
    "node2": 2,
    "node3": 0,
    "node4": 0,
    "fog1": 0,
}

# -----------------------------
# Sensor Values (Physical reality)
# -----------------------------
sensor_values = {
    "people": INITIAL_PEOPLE.get(NODE_ID, 0),
    "temperature": 22.0,
    "humidity": 45.0,
    "air_quality": 400,
    "motion": 0,
    "power": 1.5
}

# -----------------------------
# Offloaded load (Processing reality)
# -----------------------------
offloaded_in = 0

# -----------------------------
# Per-second simulation state
# -----------------------------
queue_state = 0
processing_latency_ms = 5.0

last_people_change = time.time()
previous_people = sensor_values["people"]

last_sim_update = 0.0

temp_history = deque()

last_metrics = {
    "cpu": 5.0,
    "memory": 20.0,
    "queue": 0,
    "offloaded_out": 0,
    "local_processed": 0,
    "effective_processing": 0,
    "processing_latency_ms": 5.0,
    "anomaly_multiplier": 1.0,
    "co2_anomaly": False,
    "temp_spike_anomaly": False,
    "temp_change_30s": 0.0,
    "secondary_overload": False,
    "secondary_reasons": []
}


def update_sensor_model_once_per_second():
    global last_people_change, previous_people, offloaded_in
    global queue_state, processing_latency_ms, last_sim_update, last_metrics, temp_history

    now = time.time()
    if now - last_sim_update < 1.0:
        return last_metrics

    last_sim_update = now

    people = int(sensor_values.get("people", 0))
    capacity = int(building_info.get("capacity", 1))

    if people != previous_people:
        last_people_change = now
        previous_people = people

    # Base environment model.
    sensor_values["motion"] = min(100, max(0, people * 1.2 + random.uniform(-5, 5)))
    sensor_values["temperature"] = max(18.0, min(35.0, 22.0 + people * 0.06 + random.uniform(-0.7, 0.7)))
    sensor_values["humidity"] = max(25.0, min(75.0, 45.0 + people * 0.12 + random.uniform(-2.5, 2.5)))
    sensor_values["air_quality"] = max(350, min(2500, 400 + people * 14 + random.randint(-20, 20)))
    sensor_values["power"] = max(0.5, min(15.0, 1.5 + people * 0.03 + offloaded_in * 0.025 + random.uniform(-0.1, 0.1)))

    temp_history.append((now, sensor_values["temperature"]))
    while temp_history and (now - temp_history[0][0]) > 30:
        temp_history.popleft()

    if len(temp_history) >= 2:
        temp_change_30s = temp_history[-1][1] - temp_history[0][1]
    else:
        temp_change_30s = 0.0

    co2_anomaly = sensor_values["air_quality"] > 1200
    temp_spike_anomaly = temp_change_30s > 3.5
    anomaly_multiplier = 1.0
    if co2_anomaly:
        anomaly_multiplier += 0.15
    if temp_spike_anomaly:
        anomaly_multiplier += 0.15

    effective_people_load = people
    if NODE_ROLE == "fog":
        # Fog node is processing-oriented, not a physically occupied room.
        effective_people_load = 0
        sensor_values["motion"] = 0
        sensor_values["air_quality"] = 400

    local_processed = int(max(0, effective_people_load * anomaly_multiplier))
    effective_processing = int(local_processed + offloaded_in)

    queue_state = max(0, int(effective_processing - capacity))
    cpu = min(100.0, 8 + effective_processing * 1.15 + queue_state * 0.35 + random.uniform(-2.5, 2.5))
    memory = min(100.0, 18 + effective_processing * 0.55 + queue_state * 0.18 + random.uniform(-1.5, 1.5))
    processing_latency_ms = max(3.0, 4.5 + queue_state * 0.55 + offloaded_in * 0.08 + random.uniform(-0.8, 0.8))

    secondary_reasons = []
    if cpu >= 85:
        secondary_reasons.append("cpu>=85")
    if queue_state >= 50:
        secondary_reasons.append("queue>=50")
    if memory >= 85 and cpu >= 75:
        secondary_reasons.append("memory>=85+cpu>=75")

    offloaded_out = max(0, int(max(0, people - capacity)))

    last_metrics = {
        "cpu": round(cpu, 2),
        "memory": round(memory, 2),
        "queue": int(queue_state),
        "offloaded_out": int(offloaded_out),
        "local_processed": int(local_processed),
        "effective_processing": int(effective_processing),
        "processing_latency_ms": round(processing_latency_ms, 2),
        "anomaly_multiplier": round(anomaly_multiplier, 2),
        "co2_anomaly": co2_anomaly,
        "temp_spike_anomaly": temp_spike_anomaly,
        "temp_change_30s": round(temp_change_30s, 2),
        "secondary_overload": len(secondary_reasons) > 0,
        "secondary_reasons": secondary_reasons,
    }
    return last_metrics


@app.route("/health")
def health():
    if not node_active:
        return jsonify({"status": "offline"})

    m = update_sensor_model_once_per_second()

    return jsonify({
        "node": NODE_ID,
        "role": NODE_ROLE,
        "scaling_source": "local-fog-server" if NODE_ROLE == "fog" else "edge-campus-device",
        "building": building_info,
        "status": "active",
        "cpu_percent": m["cpu"],
        "memory_percent": m["memory"],
        "queue_length": m["queue"],
        "processing_latency_ms": m["processing_latency_ms"],
        "sensor_values": sensor_values,
        "offloaded_in": int(offloaded_in),
        "offloaded_out": m["offloaded_out"],
        "local_processed": m["local_processed"],
        "effective_processing": m["effective_processing"],
        "anomaly_multiplier": m["anomaly_multiplier"],
        "co2_anomaly": m["co2_anomaly"],
        "temp_spike_anomaly": m["temp_spike_anomaly"],
        "temp_change_30s": m["temp_change_30s"],
        "secondary_overload": m["secondary_overload"],
        "secondary_reasons": m["secondary_reasons"]
    })


@app.route("/set_people", methods=["POST"])
def set_people():
    if NODE_ROLE == "fog":
        return jsonify({"people": sensor_values["people"], "message": "Fog node occupancy is fixed."})
    level = int(request.json.get("people", 0))
    sensor_values["people"] = max(0, level)
    return jsonify({"people": sensor_values["people"]})


@app.route("/add_offloaded", methods=["POST"])
def add_offloaded():
    global offloaded_in
    delta = int(request.json.get("delta", 0))
    offloaded_in = max(0, offloaded_in + delta)
    return jsonify({"offloaded_in": offloaded_in})


@app.route("/reset_offloaded", methods=["POST"])
def reset_offloaded():
    global offloaded_in
    offloaded_in = 0
    return jsonify({"offloaded_in": offloaded_in})


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
