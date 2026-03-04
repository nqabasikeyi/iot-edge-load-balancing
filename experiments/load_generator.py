import requests
import time
import random

TARGET_NODE = "http://localhost:5001"

while True:
    requests.post(f"{TARGET_NODE}/task", json={"sensor_data": random.random()})
    time.sleep(0.2)