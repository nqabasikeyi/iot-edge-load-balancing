from flask import Flask, jsonify, render_template, request
import requests
import time

app = Flask(__name__, template_folder="templates")

EDGE_NODES = ["node1:5000", "node2:5000", "node3:5000", "node4:5000"]
FOG_NODES = ["fog1:5000"]
NODES = EDGE_NODES + FOG_NODES

MAX_EVENTS = 14
BALANCE_GAP = 12
TRANSFER_STEP = 8
SENDER_TARGET_BUFFER = 3

events = []


def safe_get(url, timeout=2):
    try:
        return requests.get(url, timeout=timeout)
    except Exception:
        return None


def safe_post(url, json=None, timeout=2):
    try:
        return requests.post(url, json=json, timeout=timeout)
    except Exception:
        return None


def fetch_health(node_addr):
    start = time.time()
    response = safe_get(f"http://{node_addr}/health", timeout=2)
    latency = int((time.time() - start) * 1000)

    role = "fog" if node_addr in FOG_NODES else "edge"
    base = {
        "node": node_addr.split(":")[0],
        "address": node_addr,
        "status": "OFFLINE",
        "cpu_percent": 0,
        "memory_percent": 0,
        "queue_length": 0,
        "latency_ms": 0,
        "role": role,
        "scaling_source": "local-fog-server" if role == "fog" else "edge-campus-device",
        "building": {"capacity": 0, "name": node_addr.split(":")[0], "size": 0},
        "sensor_values": {"people": 0, "temperature": 0, "humidity": 0, "air_quality": 0, "motion": 0, "power": 0},
        "sensor_limits": {},
        "offloaded_in": 0,
        "offloaded_out": 0,
        "local_processed": 0,
        "effective_processing": 0,
        "processing_latency_ms": 0,
        "anomaly_multiplier": 1.0,
        "co2_anomaly": False,
        "temp_spike_anomaly": False,
        "temp_change_30s": 0.0,
        "secondary_overload": False,
        "secondary_reasons": [],
        "sensor_max_reached": False,
        "sensor_max_reasons": [],
        "overload_reasons": [],
        "load_score": 0.0,
        "balance_action": "idle",
        "received_from": [],
        "sent_to": [],
    }

    if not response:
        return base

    data = response.json()
    base.update(data)
    base["address"] = node_addr
    base["latency_ms"] = 0 if data.get("status") == "offline" else latency
    if data.get("status") == "offline":
        base["status"] = "OFFLINE"
    return base


def set_people(addr, value):
    return safe_post(f"http://{addr}/set_people", json={"people": int(value)}, timeout=2)


def set_sensor(addr, sensor, value):
    return safe_post(f"http://{addr}/set_sensor", json={"sensor": sensor, "value": value}, timeout=2)


def reset_offloaded(addr):
    return safe_post(f"http://{addr}/reset_offloaded", json={}, timeout=2)


def add_offloaded(addr, delta):
    return safe_post(f"http://{addr}/add_offloaded", json={"delta": int(delta)}, timeout=2)


def reset_all_offloaded():
    for node in NODES:
        reset_offloaded(node)


def add_event(sender, receiver, amount, reasons=None):
    ts = time.strftime("%H:%M:%S")
    sender_name = sender.split(":")[0]
    receiver_name = receiver.split(":")[0]
    reason_text = f" ({', '.join(reasons)})" if reasons else ""
    events.append(f"[{ts}] {sender_name}{reason_text} -> sending {amount} load to {receiver_name}")
    if len(events) > MAX_EVENTS:
        del events[0 : len(events) - MAX_EVENTS]


def sender_reasons(node):
    reasons = []
    if bool(node.get("sensor_max_reached", False)):
        reasons.extend(node.get("sensor_max_reasons", []))
    if float(node.get("cpu_percent", 0)) >= 85:
        reasons.append("cpu-high")
    if int(node.get("queue_length", 0)) >= 35:
        reasons.append("queue-high")
    return reasons


def receiver_capacity(node):
    if node.get("status") == "OFFLINE":
        return 0
    cap = int(node.get("building", {}).get("capacity", 0))
    effective = int(node.get("effective_processing", 0))
    if node.get("role") == "fog":
        return max(0, cap - effective)
    if bool(node.get("sensor_max_reached", False)):
        return 0
    if float(node.get("cpu_percent", 0)) >= 82 or int(node.get("queue_length", 0)) >= 30:
        return 0
    return max(0, cap - effective)


def load_gap(sender, receiver):
    return float(sender.get("load_score", 0)) - float(receiver.get("load_score", 0))


def redistribute_processing_load(nodes):
    by_addr = {node["address"]: node for node in nodes}

    for node in by_addr.values():
        if node.get("status") != "OFFLINE":
            node["status"] = "NORMAL" if node.get("role") != "fog" else "FOG-NORMAL"
        node["overload_reasons"] = []
        node["received_from"] = []
        node["sent_to"] = []
        node["balance_action"] = "idle"

    senders = []
    for addr in EDGE_NODES:
        node = by_addr.get(addr)
        if not node or node.get("status") == "OFFLINE":
            continue

        reasons = sender_reasons(node)
        gap_to_avg = float(node.get("load_score", 0))
        if bool(node.get("sensor_max_reached", False)) or float(node.get("cpu_percent", 0)) >= 85 or int(node.get("queue_length", 0)) >= 35:
            senders.append((addr, reasons, max(TRANSFER_STEP, int(node.get("offloaded_out", 0)))))
            node["status"] = "MAX-REACHED" if bool(node.get("sensor_max_reached", False)) else "BALANCING-SEND"
            node["overload_reasons"] = reasons
        else:
            node["overload_reasons"] = reasons

    # Also rebalance uneven loads even when no max sensor is hit.
    healthy_edges = [by_addr[a] for a in EDGE_NODES if a in by_addr and by_addr[a].get("status") != "OFFLINE"]
    if healthy_edges:
        avg_load = sum(float(n.get("load_score", 0)) for n in healthy_edges) / len(healthy_edges)
        for node in healthy_edges:
            if node["address"] in [s[0] for s in senders]:
                continue
            if float(node.get("load_score", 0)) >= avg_load + BALANCE_GAP:
                senders.append((node["address"], ["load-imbalance"], TRANSFER_STEP))
                node["status"] = "BALANCING-SEND"
                node["overload_reasons"] = ["load-imbalance"]

    seen = set()
    unique_senders = []
    for sender in senders:
        if sender[0] not in seen:
            unique_senders.append(sender)
            seen.add(sender[0])

    for sender_addr, reasons, initial_amount in unique_senders:
        sender = by_addr.get(sender_addr)
        if not sender or sender.get("status") == "OFFLINE":
            continue

        remaining = int(initial_amount)
        sender_capacity = int(sender.get("building", {}).get("capacity", 0))
        sender_effective = int(sender.get("effective_processing", 0))
        if sender_effective > sender_capacity:
            remaining = max(remaining, sender_effective - max(0, sender_capacity - SENDER_TARGET_BUFFER))

        edge_receivers = []
        for target_addr in EDGE_NODES:
            if target_addr == sender_addr:
                continue
            target = by_addr.get(target_addr)
            if not target:
                continue
            free = receiver_capacity(target)
            gap = load_gap(sender, target)
            if free > 0 and gap >= BALANCE_GAP:
                edge_receivers.append((gap, free, target_addr))
        edge_receivers.sort(reverse=True)

        for _, free, target_addr in edge_receivers:
            if remaining <= 0:
                break
            target = by_addr[target_addr]
            transfer = min(remaining, free, TRANSFER_STEP)
            if transfer <= 0:
                continue
            if not add_offloaded(target_addr, transfer):
                continue

            sender["sent_to"].append({"target": target_addr.split(":")[0], "amount": transfer})
            target["received_from"].append({"source": sender_addr.split(":")[0], "amount": transfer})
            target["balance_action"] = "receiving"
            if target.get("role") == "fog":
                target["status"] = "FOG-RECEIVING"
            else:
                target["status"] = "RECEIVING"
            add_event(sender_addr, target_addr, transfer, reasons)
            remaining -= transfer

        if remaining > 0:
            fog_receivers = []
            for target_addr in FOG_NODES:
                target = by_addr.get(target_addr)
                if not target:
                    continue
                free = receiver_capacity(target)
                if free > 0:
                    fog_receivers.append((free, target_addr))
            fog_receivers.sort(reverse=True)

            for free, target_addr in fog_receivers:
                if remaining <= 0:
                    break
                target = by_addr[target_addr]
                transfer = min(remaining, free, TRANSFER_STEP)
                if transfer <= 0:
                    continue
                if not add_offloaded(target_addr, transfer):
                    continue

                sender["sent_to"].append({"target": target_addr.split(":")[0], "amount": transfer})
                target["received_from"].append({"source": sender_addr.split(":")[0], "amount": transfer})
                target["balance_action"] = "receiving"
                target["status"] = "FOG-RECEIVING"
                add_event(sender_addr, target_addr, transfer, reasons)
                remaining -= transfer

        if sender.get("status") not in {"MAX-REACHED", "OFFLINE"}:
            sender["status"] = "BALANCING-SEND" if sender.get("sent_to") else "NORMAL"

    return list(by_addr.values())


def compute_summary(nodes):
    active = [n for n in nodes if n.get("status") != "OFFLINE"]
    if not active:
        return {
            "average_cpu": 0,
            "total_queue": 0,
            "active_nodes": 0,
            "overloaded_nodes": 0,
            "balance_score": 100,
            "total_throughput": 0,
            "edge_nodes": 0,
            "fog_nodes": 0,
        }

    cpu_values = [float(n.get("cpu_percent", 0)) for n in active]
    avg_cpu = sum(cpu_values) / len(cpu_values)
    total_queue = sum(int(n.get("queue_length", 0)) for n in active)
    total_throughput = sum(int(n.get("effective_processing", 0)) for n in active)
    overloaded = sum(1 for n in active if str(n.get("status", "")).startswith("MAX-REACHED"))

    variance = sum((cpu - avg_cpu) ** 2 for cpu in cpu_values) / len(cpu_values)
    balance_score = max(0, 100 - variance)

    return {
        "average_cpu": round(avg_cpu, 2),
        "total_queue": total_queue,
        "active_nodes": len(active),
        "overloaded_nodes": overloaded,
        "balance_score": round(balance_score, 2),
        "total_throughput": total_throughput,
        "edge_nodes": sum(1 for n in active if n.get("role") == "edge"),
        "fog_nodes": sum(1 for n in active if n.get("role") == "fog"),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/nodes")
def nodes():
    snapshot = [fetch_health(node) for node in NODES]
    reset_all_offloaded()
    updated = redistribute_processing_load(snapshot)
    refreshed = [fetch_health(node) for node in NODES]
    updated_map = {n["address"]: n for n in updated}

    for node in refreshed:
        upd = updated_map.get(node["address"], {})
        for key in ["status", "overload_reasons", "role", "scaling_source", "received_from", "sent_to", "balance_action"]:
            node[key] = upd.get(key, node.get(key))

    summary = compute_summary(refreshed)
    return jsonify({"nodes": refreshed, "system": summary, "events": events[-MAX_EVENTS:]})


@app.route("/control_people", methods=["POST"])
def control_people():
    payload = request.json or {}
    set_people(payload["node"], int(payload["people"]))
    return jsonify({"ok": True})


@app.route("/control_sensor", methods=["POST"])
def control_sensor():
    payload = request.json or {}
    set_sensor(payload["node"], payload["sensor"], payload["value"])
    return jsonify({"ok": True})


@app.route("/control_node", methods=["POST"])
def control_node():
    payload = request.json or {}
    node = payload["node"]
    action = payload["action"]
    if action == "shutdown":
        safe_post(f"http://{node}/shutdown_node", timeout=2)
    elif action == "activate":
        safe_post(f"http://{node}/activate_node", timeout=2)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7000)
