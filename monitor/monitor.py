from flask import Flask, jsonify, render_template, request
import requests
import random
import time

app = Flask(__name__, template_folder="templates")

# Edge nodes are the primary processing layer.
EDGE_NODES = ["node1:5000", "node2:5000", "node3:5000", "node4:5000"]
# Local fog node acts as nearby campus fallback capacity.
FOG_NODES = ["fog1:5000"]
NODES = EDGE_NODES + FOG_NODES

REDISTRIBUTION_DELAY = 2  # seconds
MAX_EVENTS = 12
events = []

# -----------------------------
# Secondary overload thresholds
# -----------------------------
CPU_OVERLOAD = 85
QUEUE_OVERLOAD = 50
MEMORY_OVERLOAD = 85
CPU_WITH_MEMORY_OVERLOAD = 75


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
    r = safe_get(f"http://{node_addr}/health", timeout=2)
    latency = int((time.time() - start) * 1000)

    if not r:
        role = "fog" if node_addr in FOG_NODES else "edge"
        return {
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
            "sensor_values": {
                "people": 0,
                "temperature": 0,
                "humidity": 0,
                "air_quality": 0,
                "motion": 0,
                "power": 0
            },
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
            "overload_reasons": []
        }

    data = r.json()
    data["address"] = node_addr
    data["latency_ms"] = 0 if data.get("status") == "offline" else latency

    data.setdefault("node", node_addr.split(":")[0])
    data.setdefault("building", {"capacity": 0, "name": node_addr.split(":")[0], "size": 0})
    data.setdefault("sensor_values", {"people": 0})
    data.setdefault("offloaded_in", 0)
    data.setdefault("offloaded_out", 0)
    data.setdefault("local_processed", 0)
    data.setdefault("effective_processing", 0)
    data.setdefault("processing_latency_ms", 0)
    data.setdefault("anomaly_multiplier", 1.0)
    data.setdefault("co2_anomaly", False)
    data.setdefault("temp_spike_anomaly", False)
    data.setdefault("temp_change_30s", 0.0)
    data.setdefault("secondary_overload", False)
    data.setdefault("secondary_reasons", [])
    data.setdefault("overload_reasons", [])
    data.setdefault("role", "fog" if node_addr in FOG_NODES else "edge")
    data.setdefault("scaling_source", "local-fog-server" if node_addr in FOG_NODES else "edge-campus-device")

    # Normalize for dashboard
    data["status"] = "OFFLINE" if data.get("status") == "offline" else "NORMAL"
    return data


def set_people(addr, value):
    return safe_post(f"http://{addr}/set_people", json={"people": int(value)}, timeout=2)


def reset_offloaded(addr):
    return safe_post(f"http://{addr}/reset_offloaded", json={}, timeout=2)


def add_offloaded(addr, delta):
    return safe_post(f"http://{addr}/add_offloaded", json={"delta": int(delta)}, timeout=2)


def reset_all_offloaded():
    for n in NODES:
        reset_offloaded(n)


def add_event(frm, to, amount, reasons=None):
    ts = time.strftime("%H:%M:%S")
    sender = frm.split(":")[0]
    receiver = to.split(":")[0]
    receiver_role = "FOG" if to in FOG_NODES else "EDGE"

    if reasons:
        reason_text = ", ".join(reasons)
        events.append(f"[{ts}] {sender} OVERLOAD ({reason_text}) → offloading {amount} to {receiver} [{receiver_role}]")
    else:
        events.append(f"[{ts}] {sender} OVERLOAD → offloading {amount} to {receiver} [{receiver_role}]")

    if len(events) > MAX_EVENTS:
        del events[0:len(events) - MAX_EVENTS]


def classify_overload(nd):
    cap = int(nd["building"].get("capacity", 0))
    ppl = int(nd["sensor_values"].get("people", 0))
    cpu = float(nd.get("cpu_percent", 0))
    memory = float(nd.get("memory_percent", 0))
    queue = int(nd.get("queue_length", 0))

    co2_anomaly = bool(nd.get("co2_anomaly", False))
    temp_spike_anomaly = bool(nd.get("temp_spike_anomaly", False))

    capacity_overload = cap > 0 and ppl > cap
    cpu_overload = cpu >= CPU_OVERLOAD
    queue_overload = queue >= QUEUE_OVERLOAD
    memory_supported_overload = memory >= MEMORY_OVERLOAD and cpu >= CPU_WITH_MEMORY_OVERLOAD

    overloaded = (
        capacity_overload
        or cpu_overload
        or queue_overload
        or memory_supported_overload
    )

    reasons = []

    if capacity_overload:
        reasons.append("capacity")

    if cpu_overload:
        reasons.append("cpu>=85")

    if queue_overload:
        reasons.append("queue>=50")

    if memory_supported_overload:
        reasons.append("memory>=85+cpu>=75")

    if co2_anomaly:
        reasons.append("co2-anomaly")

    if temp_spike_anomaly:
        reasons.append("temp-spike")

    return overloaded, reasons, capacity_overload


def redistribute_processing_load(nodes):
    """
    - Does not change physical people counts.
    - Uses edge-to-edge redistribution first.
    - Uses local fog fallback only when edge nodes cannot absorb more load.
    """
    by_addr = {n["address"]: n for n in nodes}

    def get_targets(exclude_addr, target_pool):
        targets = []
        for a in target_pool:
            nd = by_addr.get(a)
            if not nd or a == exclude_addr:
                continue

            if nd["status"] == "OFFLINE":
                continue

            overloaded, _, _ = classify_overload(nd)
            if overloaded:
                continue

            cap = int(nd["building"].get("capacity", 0))
            ppl = int(nd["sensor_values"].get("people", 0))
            cpu = float(nd.get("cpu_percent", 0))
            queue = int(nd.get("queue_length", 0))
            memory = float(nd.get("memory_percent", 0))

            free = cap - ppl

            # receiver should have physical space and healthy runtime state
            if free > 0 and cpu < 75 and queue < 40 and memory < 85:
                targets.append(a)

        random.shuffle(targets)
        return targets

    # start cycle: mark all active NORMAL
    for a, nd in by_addr.items():
        if nd["status"] != "OFFLINE":
            nd["status"] = "NORMAL"
            nd["overload_reasons"] = []

    # redistribute for each overloaded edge room
    for addr in EDGE_NODES:
        nd = by_addr.get(addr)
        if not nd or nd["status"] == "OFFLINE":
            continue

        overloaded, reasons, capacity_overload = classify_overload(nd)
        nd["overload_reasons"] = reasons

        if overloaded:
            nd["status"] = "OVERLOAD"

            cap = int(nd["building"].get("capacity", 0))
            ppl = int(nd["sensor_values"].get("people", 0))
            cpu = float(nd.get("cpu_percent", 0))
            queue = int(nd.get("queue_length", 0))

            if capacity_overload:
                excess = max(0, ppl - cap)
            else:
                cpu_factor = max(0, int((cpu - 70) / 5))
                queue_factor = max(0, queue // 5)
                excess = max(5, min(15, cpu_factor + queue_factor))

            time.sleep(REDISTRIBUTION_DELAY)

            # 1) Prefer peer edge nodes first.
            edge_targets = get_targets(addr, EDGE_NODES)
            while excess > 0 and edge_targets:
                taddr = edge_targets.pop()
                tnd = by_addr[taddr]

                tcap = int(tnd["building"].get("capacity", 0))
                tppl = int(tnd["sensor_values"].get("people", 0))
                free = tcap - tppl

                if free <= 0:
                    continue

                transfer = min(excess, free)

                ok = add_offloaded(taddr, transfer)
                if not ok:
                    tnd["status"] = "OFFLINE"
                    continue

                add_event(addr, taddr, transfer, reasons)
                tnd["status"] = "REC:OVERLOAD" if "OVERLOAD" in str(tnd["status"]) else "RECEIVING"
                excess -= transfer

            # 2) If edge layer is saturated, use local fog node fallback.
            if excess > 0:
                fog_targets = get_targets(addr, FOG_NODES)
                while excess > 0 and fog_targets:
                    taddr = fog_targets.pop()
                    tnd = by_addr[taddr]

                    tcap = int(tnd["building"].get("capacity", 0))
                    tppl = int(tnd["sensor_values"].get("people", 0))
                    free = tcap - tppl

                    if free <= 0:
                        continue

                    transfer = min(excess, free)
                    ok = add_offloaded(taddr, transfer)
                    if not ok:
                        tnd["status"] = "OFFLINE"
                        continue

                    add_event(addr, taddr, transfer, reasons)
                    tnd["status"] = "FOG-RECEIVING"
                    excess -= transfer

            nd["status"] = "OVERLOAD"

    return list(by_addr.values())


def compute_summary(nodes):
    active = [n for n in nodes if n["status"] != "OFFLINE"]
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
    overloaded = sum(1 for n in active if "OVERLOAD" in str(n["status"]))

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
    snapshot = [fetch_health(n) for n in NODES]

    reset_all_offloaded()
    updated = redistribute_processing_load(snapshot)

    refreshed = [fetch_health(n) for n in NODES]
    updated_map = {n["address"]: n for n in updated}

    for n in refreshed:
        upd = updated_map.get(n["address"], {})
        n["status"] = upd.get("status", n["status"])
        n["overload_reasons"] = upd.get("overload_reasons", [])
        n["role"] = upd.get("role", n.get("role"))
        n["scaling_source"] = upd.get("scaling_source", n.get("scaling_source"))

    summary = compute_summary(refreshed)
    return jsonify({"nodes": refreshed, "system": summary, "events": events[-MAX_EVENTS:]})


@app.route("/control_people", methods=["POST"])
def control_people():
    payload = request.json
    node = payload["node"]
    people = int(payload["people"])
    set_people(node, people)
    return jsonify({"ok": True})


@app.route("/control_node", methods=["POST"])
def control_node():
    payload = request.json
    node = payload["node"]
    action = payload["action"]

    if action == "shutdown":
        safe_post(f"http://{node}/shutdown_node", timeout=2)
    elif action == "activate":
        safe_post(f"http://{node}/activate_node", timeout=2)

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7000)
