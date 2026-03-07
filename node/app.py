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
}
building_info = BUILDINGS.get(NODE_ID, {"name": "Unknown", "size": 100, "capacity": 20})

# -----------------------------
# Initial Occupancy per Building
# -----------------------------
INITIAL_PEOPLE = {
    "node1": 10,  # Library
    "node2": 2,   # Lecturer Office
    "node3": 0,   # Laboratory
    "node4": 0    # Classroom
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

# stores (timestamp, temperature) for last 30 seconds
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

# -----------------------------
# Simulation Model (updates once per second)
# -----------------------------
def update_sensor_model_once_per_second():
    global last_people_change, previous_people, offloaded_in
    global queue_state, processing_latency_ms, last_sim_update, last_metrics, temp_history

    now = time.time()
    if now - last_sim_update < 1.0:
        return last_metrics  # no update yet

    last_sim_update = now

    people = int(sensor_values.get("people", 0))
    capacity = int(building_info.get("capacity", 1))

    # Track change time for motion spikes
    if people != previous_people:
        last_people_change = now
        previous_people = people

    elapsed = now - last_people_change

    # Motion spike for 5 seconds after change
    if elapsed < 5:
        motion = people * 0.4
    else:
        motion = people * 0.05 + random.uniform(-2, 2)
    sensor_values["motion"] = max(0, round(motion, 2))

    # -----------------------------
    # Physical vs processing
    # -----------------------------
    offloaded_out = max(0, people - capacity)     # to be offloaded
    local_processed = min(people, capacity)       # local processing limited by cap
    effective_processing = local_processed + int(offloaded_in)

    # -----------------------------
    # Environmental effects (physical only)
    # -----------------------------
    occupancy_ratio = people / capacity if capacity > 0 else 0
    sensor_values["air_quality"] = 400 + (people * 15)
    sensor_values["temperature"] = round(22 + (occupancy_ratio * 8), 2)
    sensor_values["humidity"] = round(40 + (occupancy_ratio * 20), 2)
    sensor_values["power"] = round(1.2 + (people * 0.08), 2)

    # -----------------------------
    # Track temperature change over 30s
    # -----------------------------
    current_temp = sensor_values["temperature"]
    temp_history.append((now, current_temp))

    while temp_history and (now - temp_history[0][0] > 30):
        temp_history.popleft()

    oldest_temp = temp_history[0][1] if temp_history else current_temp
    temp_change_30s = abs(current_temp - oldest_temp)

    # -----------------------------
    # Anomaly multiplier
    # -----------------------------
    co2_anomaly = sensor_values["air_quality"] > 1200
    temp_spike_anomaly = temp_change_30s > 2.0

    anomaly_multiplier = 1.0
    if co2_anomaly or temp_spike_anomaly:
        anomaly_multiplier = 1.25  # CPU increases faster / overload earlier

    # -----------------------------
    # CPU / Memory with baseline
    # -----------------------------
    BASE_CPU = 5.0
    BASE_MEM = 20.0

    ratio = effective_processing / capacity if capacity > 0 else 0

    if ratio <= 1:
        cpu = BASE_CPU + (ratio * 75)  # around 80% near capacity
    else:
        cpu = 80 + ((effective_processing - capacity) * 0.8)

    # anomaly increases CPU faster
    cpu = cpu * anomaly_multiplier
    cpu = min(cpu, 95)

    # include queue impact slightly in memory
    memory = BASE_MEM + (cpu * 0.6) + (queue_state * 0.15)
    memory = min(memory, 90)

    # -----------------------------
    # Queue dynamics (persists + drains)
    # -----------------------------
    arrivals = offloaded_out + int(offloaded_in * 0.6)

    # service rate drops when busy
    service = 6 if cpu < 70 else 3

    # anomaly reduces service slightly
    if anomaly_multiplier > 1.0:
        service = max(2, service - 1)

    queue_state = max(0, queue_state + arrivals - service)
    queue = int(queue_state)

    # -----------------------------
    # Processing latency model (ms)
    # -----------------------------
    processing_latency_ms = 5 + (cpu * 1.1) + (queue * 0.9) + random.uniform(0, 5)
    processing_latency_ms = min(processing_latency_ms, 500)

    # -----------------------------
    # Secondary overload rules
    # -----------------------------
    secondary_reasons = []

    if cpu >= 85:
        secondary_reasons.append("cpu>=85")

    if queue >= 50:
        secondary_reasons.append("queue>=50")

    if memory >= 85 and cpu >= 75:
        secondary_reasons.append("memory>=85_and_cpu>=75")

    secondary_overload = len(secondary_reasons) > 0

    last_metrics = {
        "cpu": round(cpu, 2),
        "memory": round(memory, 2),
        "queue": queue,
        "offloaded_out": int(offloaded_out),
        "local_processed": int(local_processed),
        "effective_processing": int(effective_processing),
        "processing_latency_ms": round(processing_latency_ms, 2),
        "anomaly_multiplier": anomaly_multiplier,
        "co2_anomaly": co2_anomaly,
        "temp_spike_anomaly": temp_spike_anomaly,
        "temp_change_30s": round(temp_change_30s, 2),
        "secondary_overload": secondary_overload,
        "secondary_reasons": secondary_reasons
    }
    return last_metrics


# -----------------------------
# Health Endpoint
# -----------------------------
@app.route("/health", methods=["GET"])
def health():
    global node_active, offloaded_in, queue_state

    if not node_active:
        return jsonify({
            "node": NODE_ID,
            "building": building_info,
            "status": "offline",
            "cpu_percent": 0,
            "memory_percent": 0,
            "queue_length": 0,
            "processing_latency_ms": 0,
            "sensor_values": sensor_values,
            "offloaded_in": 0,
            "offloaded_out": 0,
            "local_processed": 0,
            "effective_processing": 0,
            "anomaly_multiplier": 1.0,
            "co2_anomaly": False,
            "temp_spike_anomaly": False,
            "temp_change_30s": 0.0,
            "secondary_overload": False,
            "secondary_reasons": []
        })

    m = update_sensor_model_once_per_second()

    return jsonify({
        "node": NODE_ID,
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


# -----------------------------
# People Control (slider)
# -----------------------------
@app.route("/set_people", methods=["POST"])
def set_people():
    level = int(request.json.get("people", 0))
    sensor_values["people"] = max(0, level)
    return jsonify({"people": sensor_values["people"]})


# -----------------------------
# Offloaded Load Control (used by monitor)
# -----------------------------
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


# -----------------------------
# Node Control
# -----------------------------
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


# -----------------------------
# Start Server
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)