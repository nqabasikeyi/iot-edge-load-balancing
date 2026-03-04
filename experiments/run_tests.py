import subprocess
import time

print("Starting load test...")
subprocess.Popen(["python", "load_generator.py"])
time.sleep(60)
print("Test completed.")