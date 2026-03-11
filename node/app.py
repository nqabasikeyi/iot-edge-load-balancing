from flask import Flask, request, jsonify
import os
import time
import random
from collections import deque

app = Flask(__name__)

NODE_ID = os.getenv("NODE_ID", "node1")
NODE_ROLE = os.getenv("NODE_ROLE", "edge")
PORT = int(os.getenv("PORT", 5000))

node_active = True

BUILDINGS = {
    "node1": {"name": "Library", "size": 280, "capacity": 80},
    "node2": {"name": "Lecturer Office", "size": 40, "capacity": 15},
    "node3": {"name": "Laboratory", "size": 160, "capacity": 50},
    "node4": {"name": "Classroom", "size": 200, "capacity": 70},
    "fog1": {"name": "Campus Fog Server", "size": 20, "capacity": 150},
}
building_info = BUILDINGS.get(NODE_ID, {"name": "Unknown", "size": 100, "capacity": 20})

INITIAL_PEOPLE = {
    "node1": 10,
    "node2": 2,
    "node3": 0,
    "node4": 0,
    "fog1": 0,
}

SENSOR_LIMITS = {
    "people": {"min": 0, "max": int(building_info.get("capacity", 20))},
    "temperature": {"min": 18.0, "max": 40.0},
    "humidity": {"min": 25.0, "max": 90.0},
    "air_quality": {"min": 350, "max": 2000},
    "motion": {"min": 0.0, "max": 100.0},
    "power": {"min": 0.5, "max": 15.0},
}

sensor_values = {
    "people": INITIAL_PEOPLE.get(NODE_ID, 0),
    "temperature": 22.0,
    "humidity": 45.0,
    "air_quality": 400,
    "motion": 10.0,
    "power": 1.5,
}

sensor_override_until = {
    "temperature": 0.0,
    "humidity": 0.0,
    "air_quality": 0.0,
    "motion": 0.0,
    "power": 0.0,
}

offloaded_in = 0
queue_state = 0
processing_latency_ms = 5.0
last_sim_update = 0.0
previous_people = sensor_values["people"]
temp_history = deque()

last_metrics = {
    "cpu": 5.0,
    "memory": 20.0,
    "queue": 0,
    "load_score": 0.0,
    "offloaded_out": 0,
    "local_processed": 0,
    "effective_processing": 0,
    "processing_latency_ms": 5.0,
    "anomaly_multiplier": 1.0,
    "co2_anomaly": False,
    "temp_spike_anomaly": False,
    "temp_change_30s": 0.0,
    "secondary_overload": False,
    "secondary_reasons": [],
    "sensor_max_reached": False,
    "sensor_max_reasons": [],
}


def clamp(sensor, value):
    cfg = SENSOR_LIMITS[sensor]
    return max(cfg["min"], min(cfg["max"], value))


def ratio(sensor, value):
    cfg = SENSOR_LIMITS[sensor]
    span = cfg["max"] - cfg["min"]
    if span == 0:
        return 0.0
    return max(0.0, min(1.0, (value - cfg["min"]) / span))


def apply_people_relationships(old_people, new_people):
    """
    People influence the environment, but are not the main load source.
    """
    if NODE_ROLE == "fog":
        return

    delta = new_people - old_people
    if delta == 0:
        return

    sensor_values["temperature"] = clamp("temperature", sensor_values["temperature"] + (delta * 0.06))
    sensor_values["humidity"] = clamp("humidity", sensor_values["humidity"] + (delta * 0.18))
    sensor_values["air_quality"] = clamp("air_quality", sensor_values["air_quality"] + (delta * 14))
    sensor_values["motion"] = clamp("motion", sensor_values["motion"] + (delta * 1.10))
    sensor_values["power"] = clamp("power", sensor_values["power"] + (delta * 0.03))


def set_sensor_override(sensor, value):
    if sensor not in SENSOR_LIMITS:
        return False, "Unknown sensor"

    if NODE_ROLE == "fog" and sensor in {"people", "temperature", "humidity", "air_quality", "motion"}:
        return False, "Fog node environmental sensors are fixed."

    if sensor == "people":
        value = int(clamp("people", int(value)))
        old_people = int(sensor_values["people"])
        sensor_values["people"] = value
        apply_people_relationships(old_people, value)
        return True, value

    if sensor == "air_quality":
        value = int(clamp(sensor, int(value)))
    else:
        value = float(clamp(sensor, float(value)))

    sensor_values[sensor] = value
    sensor_override_until[sensor] = time.time() + 25

    # Dynamic sensor relationships
    if sensor == "temperature":
        sensor_values["humidity"] = clamp(
            "humidity",
            sensor_values["humidity"] + ((value - 22.0) * 0.10)
        )
        sensor_values["power"] = clamp(
            "power",
            sensor_values["power"] + ((value - 22.0) * 0.05)
        )

    elif sensor == "humidity":
        sensor_values["air_quality"] = int(clamp(
            "air_quality",
            sensor_values["air_quality"] + ((value - 45.0) * 5.0)
        ))

    elif sensor == "air_quality":
        sensor_values["humidity"] = clamp(
            "humidity",
            sensor_values["humidity"] + ((value - 400.0) / 260.0)
        )

    elif sensor == "motion":
        sensor_values["power"] = clamp(
            "power",
            sensor_values["power"] + ((value / 100.0) * 0.65)
        )
        sensor_values["temperature"] = clamp(
            "temperature",
            sensor_values["temperature"] + ((value / 100.0) * 0.45)
        )

    elif sensor == "power":
        sensor_values["temperature"] = clamp(
            "temperature",
            sensor_values["temperature"] + (value * 0.06)
        )

    return True, value


def drift_towards(current, target, step):
    if current < target:
        return min(target, current + step)
    return max(target, current - step)


def update_sensor_model_once_per_second():
    global offloaded_in, queue_state, processing_latency_ms, last_sim_update, last_metrics, previous_people

    now = time.time()
    if now - last_sim_update < 1.0:
        return last_metrics
    last_sim_update = now

    people = int(sensor_values.get("people", 0))
    capacity = int(building_info.get("capacity", 1))

    if NODE_ROLE == "fog":
        people = 0
        sensor_values["people"] = 0
        sensor_values["motion"] = 0.0
        sensor_values["temperature"] = 20.0
        sensor_values["humidity"] = 35.0
        sensor_values["air_quality"] = 400
        sensor_values["power"] = clamp("power", 2.5 + offloaded_in * 0.04)
    else:
        if people != previous_people:
            previous_snapshot = previous_people
            previous_people = people
            apply_people_relationships(previous_snapshot, people)

        base_targets = {
            "temperature": clamp("temperature", 22.0 + people * 0.05 + random.uniform(-0.20, 0.20)),
            "humidity": clamp("humidity", 45.0 + people * 0.14 + random.uniform(-0.8, 0.8)),
            "air_quality": int(clamp("air_quality", 400 + people * 10 + random.randint(-6, 6))),
            "motion": clamp("motion", people * 1.0 + random.uniform(-2.0, 2.0)),
            "power": clamp("power", 1.5 + people * 0.025 + offloaded_in * 0.02 + random.uniform(-0.05, 0.05)),
        }

        for sensor, target in base_targets.items():
            if now < sensor_override_until[sensor]:
                continue

            if sensor == "air_quality":
                sensor_values[sensor] = int(drift_towards(sensor_values[sensor], target, 10))
            elif sensor == "motion":
                sensor_values[sensor] = clamp(sensor, drift_towards(sensor_values[sensor], target, 2.2))
            elif sensor == "power":
                sensor_values[sensor] = clamp(sensor, drift_towards(sensor_values[sensor], target, 0.14))
            elif sensor == "humidity":
                sensor_values[sensor] = clamp(sensor, drift_towards(sensor_values[sensor], target, 0.9))
            else:
                sensor_values[sensor] = clamp(sensor, drift_towards(sensor_values[sensor], target, 0.25))

        sensor_values["humidity"] = clamp(
            "humidity",
            sensor_values["humidity"] + ((sensor_values["air_quality"] - 400) / 1200.0) * 0.18,
        )
        sensor_values["temperature"] = clamp(
            "temperature",
            sensor_values["temperature"] + (sensor_values["power"] / 15.0) * 0.06,
        )

    temp_history.append((now, float(sensor_values["temperature"])))
    while temp_history and (now - temp_history[0][0]) > 30:
        temp_history.popleft()
    temp_change_30s = (temp_history[-1][1] - temp_history[0][1]) if len(temp_history) >= 2 else 0.0

    co2_anomaly = int(sensor_values["air_quality"]) >= 1200
    temp_spike_anomaly = temp_change_30s >= 3.0

    # MAX-REACHED becomes true if ANY slider reaches its maximum.
    max_reasons = []
    if NODE_ROLE != "fog":
        if int(sensor_values["people"]) >= SENSOR_LIMITS["people"]["max"]:
            max_reasons.append("people=max")
        if float(sensor_values["temperature"]) >= SENSOR_LIMITS["temperature"]["max"]:
            max_reasons.append("temperature=max")
        if float(sensor_values["humidity"]) >= SENSOR_LIMITS["humidity"]["max"]:
            max_reasons.append("humidity=max")
        if int(sensor_values["air_quality"]) >= SENSOR_LIMITS["air_quality"]["max"]:
            max_reasons.append("co2=max")
        if float(sensor_values["motion"]) >= SENSOR_LIMITS["motion"]["max"]:
            max_reasons.append("motion=max")
        if float(sensor_values["power"]) >= SENSOR_LIMITS["power"]["max"]:
            max_reasons.append("power=max")

    sensor_max_reached = len(max_reasons) >= 1

    anomaly_multiplier = 1.0
    if co2_anomaly:
        anomaly_multiplier += 0.08
    if temp_spike_anomaly:
        anomaly_multiplier += 0.08
    if sensor_max_reached:
        anomaly_multiplier += 0.12

    if NODE_ROLE == "fog":
        local_processed = 0
        effective_processing = int(offloaded_in)
    else:
        people_ratio = people / max(1, capacity)
        temp_ratio = ratio("temperature", sensor_values["temperature"])
        humidity_ratio = ratio("humidity", sensor_values["humidity"])
        air_ratio = ratio("air_quality", sensor_values["air_quality"])
        motion_ratio = ratio("motion", sensor_values["motion"])
        power_ratio = ratio("power", sensor_values["power"])

        demand_ratio = (
            (temp_ratio * 0.22)
            + (humidity_ratio * 0.17)
            + (air_ratio * 0.22)
            + (motion_ratio * 0.17)
            + (power_ratio * 0.12)
            + (people_ratio * 0.10)
        )

        local_processed = int(capacity * demand_ratio * anomaly_multiplier)
        effective_processing = int(local_processed + offloaded_in)

    safe_capacity = int(capacity * 0.90)
    queue_state = max(0, int(effective_processing - safe_capacity))

    if NODE_ROLE == "fog":
        base_cpu = 10 + (effective_processing / max(1, capacity)) * 55
    else:
        base_cpu = 12 + (effective_processing / max(1, capacity)) * 68

    cpu = base_cpu + (queue_state * 0.18) + random.uniform(-1.2, 1.2)
    cpu = min(96.0, max(5.0, cpu))

    memory = 18 + (effective_processing / max(1, capacity)) * 42 + (queue_state * 0.10) + random.uniform(-0.8, 0.8)
    memory = min(92.0, max(10.0, memory))

    processing_latency_ms = 4.0 + (queue_state * 0.28) + (offloaded_in * 0.06) + random.uniform(-0.3, 0.3)
    processing_latency_ms = max(3.0, processing_latency_ms)

    secondary_reasons = []
    if cpu >= 85:
        secondary_reasons.append("cpu>=85")
    if queue_state >= max(5, int(capacity * 0.12)):
        secondary_reasons.append("queue-high")
    if memory >= 80 and cpu >= 75:
        secondary_reasons.append("memory>=80+cpu>=75")

    load_score = round(
        (cpu * 0.42) + (queue_state * 0.9) + (offloaded_in * 0.45) + (local_processed * 0.25),
        2,
    )

    offloaded_out = max(0, int(effective_processing - safe_capacity)) if NODE_ROLE != "fog" else 0

    last_metrics = {
        "cpu": round(cpu, 2),
        "memory": round(memory, 2),
        "queue": int(queue_state),
        "load_score": load_score,
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
        "sensor_max_reached": sensor_max_reached,
        "sensor_max_reasons": max_reasons,
    }
    return last_metrics


@app.route("/health")
def health():
    if not node_active:
        return jsonify({"status": "offline"})

    m = update_sensor_model_once_per_second()
    status = "MAX-REACHED" if m["sensor_max_reached"] and NODE_ROLE != "fog" else "active"

    return jsonify({
        "node": NODE_ID,
        "role": NODE_ROLE,
        "scaling_source": "local-fog-server" if NODE_ROLE == "fog" else "edge-campus-device",
        "building": building_info,
        "status": status,
        "cpu_percent": m["cpu"],
        "memory_percent": m["memory"],
        "queue_length": m["queue"],
        "load_score": m["load_score"],
        "processing_latency_ms": m["processing_latency_ms"],
        "sensor_values": sensor_values,
        "sensor_limits": SENSOR_LIMITS,
        "offloaded_in": int(offloaded_in),
        "offloaded_out": m["offloaded_out"],
        "local_processed": m["local_processed"],
        "effective_processing": m["effective_processing"],
        "anomaly_multiplier": m["anomaly_multiplier"],
        "co2_anomaly": m["co2_anomaly"],
        "temp_spike_anomaly": m["temp_spike_anomaly"],
        "temp_change_30s": m["temp_change_30s"],
        "secondary_overload": m["secondary_overload"],
        "secondary_reasons": m["secondary_reasons"],
        "sensor_max_reached": m["sensor_max_reached"],
        "sensor_max_reasons": m["sensor_max_reasons"],
    })


@app.route("/set_people", methods=["POST"])
def set_people():
    ok, result = set_sensor_override("people", request.json.get("people", 0))
    if not ok:
        return jsonify({"error": result}), 400
    return jsonify({"people": sensor_values["people"]})


@app.route("/set_sensor", methods=["POST"])
def set_sensor():
    payload = request.json or {}
    sensor = str(payload.get("sensor", "")).strip()
    value = payload.get("value", 0)
    ok, result = set_sensor_override(sensor, value)
    if not ok:
        return jsonify({"error": result}), 400
    return jsonify({"sensor": sensor, "value": result, "sensor_values": sensor_values})


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
