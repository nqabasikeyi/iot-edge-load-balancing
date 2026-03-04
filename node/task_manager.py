import threading
import time
import uuid

class TaskManager:
    def __init__(self):
        self.tasks = {}
        self.lock = threading.Lock()

    def create_task(self, payload):
        task_id = str(uuid.uuid4())
        self.tasks[task_id] = {
            "status": "processing",
            "payload": payload
        }
        threading.Thread(target=self._process_task, args=(task_id,), daemon=True).start()
        return task_id

    def _process_task(self, task_id):
        # Simulate CPU intensive work
        total = 0
        for i in range(10_000_000):
            total += i % 7

        with self.lock:
            self.tasks[task_id]["status"] = "completed"

    def get_status(self, task_id):
        return self.tasks.get(task_id, None)

    def get_queue_length(self):
        return len([t for t in self.tasks.values() if t["status"] == "processing"])