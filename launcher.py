import os
import sys
import time
import socket
import webbrowser
import threading
import uvicorn
from main import app

# PyInstaller Windowed மோடில் கிராஷ் ஆகாமல் தடுக்கும் பாதுகாப்பு
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

def check_port_ready(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(('127.0.0.1', port)) == 0

def launch_browser():
    port = 8000
    for _ in range(25):
        time.sleep(0.4)
        if check_port_ready(port):
            webbrowser.open(f"http://127.0.0.1:{port}")
            break

def start_backend():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")

if __name__ == "__main__":
    t = threading.Thread(target=launch_browser, daemon=True)
    t.start()
    start_backend()