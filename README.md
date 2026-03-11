# 🧠 Smart Campus Distributed Load Balancing System

Welcome to the **Smart Campus Distributed System** project!  
This project simulates a **distributed edge–fog computing environment** where smart campus buildings dynamically manage computational workloads using environmental sensor data.

The system demonstrates how multiple nodes collaborate to **balance workloads before overload occurs**, ensuring stability and performance transparency in a distributed environment.

---

# 📸 Screenshots

Add screenshots of your dashboard here.

![Dashboard](./screenshots/dashboard.png)

---

# 🏗 System Architecture

The system simulates a **smart campus distributed computing environment** composed of several nodes.

| Node | Role | Location |
|-----|------|------|
| node1 | Edge Node | Library |
| node2 | Edge Node | Lecturer Office |
| node3 | Edge Node | Laboratory |
| node4 | Edge Node | Classroom |
| fog1 | Fog Node | Campus Fog Server |

## Edge Nodes

Edge nodes represent **smart buildings equipped with sensors**.  
Each node processes environmental data locally and generates workloads based on sensor readings.

## Fog Node

The fog node acts as a **central processing fallback server**.  
If edge nodes cannot handle additional workload, tasks are redirected to the fog node.

---

# 🌡 Sensor Simulation

Each building node simulates several environmental and activity sensors.

| Sensor | Description |
|------|------|
| People | Number of occupants in the building |
| Temperature | Indoor temperature level |
| Humidity | Air moisture level |
| CO₂ | Air quality level |
| Motion | Activity detection level |
| Power | Device energy consumption |

## Sensor Relationships

The sensors dynamically influence one another.

Examples:

- Increasing **people** increases **temperature, humidity, and CO₂**
- Higher **motion** increases **power consumption**
- Increased **power consumption** raises **temperature**

These interactions simulate **real smart building behaviour**.

---

# ⚠️ Node Status Types

Nodes can operate in several states.

| Status | Meaning |
|------|------|
| ACTIVE | Normal operation |
| MAX-REACHED | A sensor has reached its maximum threshold |
| BALANCING-SEND | Node sending workload to another node |
| RECEIVING | Node receiving workload from another node |
| FOG-RECEIVING | Fog server receiving excess workload |

---

# ⚖️ Load Balancing Strategy

The monitoring service continuously evaluates node performance using metrics such as:

- CPU usage
- Memory usage
- Queue length
- Sensor activity

When imbalance occurs:

1. The **node with highest load becomes the sender**
2. Nodes with lower load become **receivers**
3. Processing tasks are redistributed

If all edge nodes are heavily loaded, the **fog node receives the excess workload**.

---

# 🚀 Installation

Follow these steps to run the system locally.

## 1️⃣ Clone the Repository

```bash
git clone https://github.com/ynqabasikeyi/iot-edge-load-balancing.git
cd iot-edge-load-balancing

## 2️⃣ Install Docker

Ensure **Docker** and **Docker Compose** are installed.

Download Docker here:

https://www.docker.com/products/docker-desktop/

---

## 3️⃣ Start the Distributed System

Run the following command:

```bash
docker-compose up --build

This will start:

- Edge nodes
- Fog node
- Monitoring service
- Dashboard

---

## 🌐 Open the Dashboard

Open your browser and go to:

```bash
http://localhost:7000
```

The dashboard allows you to:

- Adjust sensor sliders
- Simulate building activity
- Monitor node metrics
- Observe load balancing events

---

## 📦 Usage

Using the dashboard, you can simulate various distributed system scenarios.

### Example Scenario

1. Increase **CO₂** or **temperature** in the **Library node**.
2. The node reaches its sensor threshold.
3. The node status becomes **MAX-REACHED**.
4. The monitoring service redistributes workload to another node.
5. The receiving node displays **RECEIVING** status.

This demonstrates **dynamic distributed load balancing**.

---

## 🛠 Technologies Used

- Python
- Flask
- Docker
- Docker Compose
- HTML / JavaScript Dashboard

---

## 🎓 Educational Purpose

This system demonstrates important **Distributed Systems concepts**, including:

- Edge Computing
- Fog Computing
- Distributed Monitoring
- Load Balancing
- Sensor-Driven Processing
- Performance Transparency
- Fault-Tolerant Architecture

The project acts as a **simulation platform for studying distributed resource management and adaptive workload balancing**.

---

## 🔮 Future Improvements

Possible future improvements include:

- Machine learning based workload prediction
- Advanced anomaly detection
- Real IoT device integration
- Decentralized monitoring architecture
- Kubernetes deployment
