from flask import Flask, render_template, jsonify
import requests

app = Flask(__name__)

NODES = [
    "node1:5001",
    "node2:5002",
    "node3:5003",
    "node4:5004"
]

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/nodes")
def get_nodes():
    data = []
    for node in NODES:
        try:
            r = requests.get(f"http://{node}/health")
            node_data = r.json()
            node_data["address"] = node
            data.append(node_data)
        except:
            data.append({"address": node, "status": "offline"})
    return jsonify(data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7000)