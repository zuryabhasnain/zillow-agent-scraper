#!/usr/bin/env python3
import os
import sys
import time
import threading
import re
import subprocess
import urllib.request

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
URL_FILE = os.path.join(BASE_DIR, "LIVE_URL.txt")

def start_api_server():
    print(f"[Server] Starting FastAPI Scraper Server on port {PORT}...", flush=True)
    server_script = os.path.join(BASE_DIR, "server.py")
    python_bin = sys.executable
    subprocess.run([python_bin, server_script])

def keep_alive_worker(url, stop_event):
    print(f"[KeepAlive] Health check pinger started for {url}", flush=True)
    while not stop_event.is_set():
        try:
            req = urllib.request.Request(
                f"{url}/api/metrics",
                headers={"User-Agent": "Mozilla/5.0 (ZillowScraper-KeepAlive/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                _ = resp.read(512)
        except Exception:
            pass
        for _ in range(15):
            if stop_event.is_set():
                break
            time.sleep(1)

def run_tunnel():
    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=999",
        "-R", f"80:127.0.0.1:{PORT}",
        "nokey@localhost.run"
    ]

    while True:
        print("[Tunnel] Connecting to localhost.run relay...", flush=True)
        proc = subprocess.Popen(
            ssh_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        tunnel_url = None
        stop_event = threading.Event()
        keepalive_thread = None

        try:
            for line in iter(proc.stdout.readline, ''):
                sys.stdout.write(line)
                sys.stdout.flush()

                match = re.search(r'https://[a-zA-Z0-9\-]+\.lhr\.life', line)
                if match and not tunnel_url:
                    tunnel_url = match.group(0)
                    print(f"\n{'='*70}", flush=True)
                    print(f"🎉 ZILLOW LEAD SCRAPER LIVE PUBLIC LINK IS READY:", flush=True)
                    print(f"👉 {tunnel_url}", flush=True)
                    print(f"{'='*70}\n", flush=True)
                    with open(URL_FILE, "w") as f:
                        f.write(tunnel_url + "\n")

                    keepalive_thread = threading.Thread(
                        target=keep_alive_worker,
                        args=(tunnel_url, stop_event),
                        daemon=True
                    )
                    keepalive_thread.start()

            proc.wait()
            print(f"[Tunnel] Disconnected with code {proc.returncode}", flush=True)
        except Exception as e:
            print(f"[Tunnel] Exception: {e}", flush=True)
        finally:
            stop_event.set()
            if keepalive_thread and keepalive_thread.is_alive():
                keepalive_thread.join(timeout=2)
            if proc.poll() is None:
                proc.terminate()

        print("[Tunnel] Auto-reconnecting in 3 seconds...", flush=True)
        time.sleep(3)

if __name__ == "__main__":
    server_thread = threading.Thread(target=start_api_server, daemon=True)
    server_thread.start()
    time.sleep(2)
    run_tunnel()
