import select
import socket
import threading
import time
import sys
import paramiko

# Set console encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def handler(chan, host, port):
    sock = socket.socket()
    try:
        sock.connect((host, port))
    except Exception as e:
        print(f"[Tunnel] Local connect error to {host}:{port}: {e}")
        chan.close()
        return

    try:
        while True:
            r, w, x = select.select([sock, chan], [], [], 1.0)
            if sock in r:
                data = sock.recv(4096)
                if not data:
                    break
                chan.sendall(data)
            if chan in r:
                data = chan.recv(4096)
                if not data:
                    break
                sock.sendall(data)
    except Exception:
        pass
    finally:
        chan.close()
        sock.close()

def reverse_forward_loop(server_port, remote_host, remote_port, transport, stop_event):
    transport.request_port_forward("", server_port)
    print(f"[Tunnel] Jetson:{server_port} -> Windows:{remote_host}:{remote_port} aktif.")
    while not stop_event.is_set():
        chan = transport.accept(1.0)
        if chan is None:
            continue
        thr = threading.Thread(
            target=handler, args=(chan, remote_host, remote_port), daemon=True
        )
        thr.start()

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print("[Jetson] Baglaniliyor: 192.168.1.111...")
    ssh.connect("192.168.1.111", username="okistech", password="123456", timeout=10)
    transport = ssh.get_transport()

    stop_event = threading.Event()
    tunnel_thread = threading.Thread(
        target=reverse_forward_loop,
        args=(8420, "127.0.0.1", 8420, transport, stop_event),
        daemon=True,
    )
    tunnel_thread.start()

    time.sleep(1)

    print("[Jetson] Robot ajani baslatiliyor...")
    cmd = "/home/okistech/Desktop/astr1/.venv/bin/python -u /home/okistech/Desktop/astr1/scripts/astro_web_agent.py --gateway ws://127.0.0.1:8420"
    stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)

    try:
        for line in iter(stdout.readline, ""):
            print(f"[Jetson Robot] {line.strip()}")
            sys.stdout.flush()
    except KeyboardInterrupt:
        print("[Jetson] Durduruluyor...")
    finally:
        stop_event.set()
        ssh.close()

if __name__ == "__main__":
    main()
