"""
ASTRO V1 — Jetson <-> Windows Guvenli Port Koprusu (SSH Reverse Tunnel).
Jetson uzerindeki 127.0.0.1:8420 baglantilarini Windows uzerindeki 127.0.0.1:8420 portuna yonlendirir.
"""

import select
import socket
import threading
import time
import sys
import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def handler(chan, host, port):
    sock = socket.socket()
    try:
        sock.connect((host, port))
    except Exception as e:
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
    print(f"✅ [Tunnel Aktif] Jetson:{server_port} -> Windows:{remote_host}:{remote_port}")
    print("Jetson uzerinden 'bash baslat_web_baglanti.sh' veya './baslat_hepsi.sh' komutunu verebilirsiniz.")
    while not stop_event.is_set():
        chan = transport.accept(1.0)
        if chan is None:
            continue
        thr = threading.Thread(
            target=handler, args=(chan, remote_host, remote_port), daemon=True
        )
        thr.start()

def main():
    while True:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            print("🔌 Jetson'a baglaniliyor (192.168.1.111:22)...")
            ssh.connect("192.168.1.111", username="okistech", password="123456", timeout=10)
            transport = ssh.get_transport()

            stop_event = threading.Event()
            tunnel_thread = threading.Thread(
                target=reverse_forward_loop,
                args=(8420, "127.0.0.1", 8420, transport, stop_event),
                daemon=True,
            )
            tunnel_thread.start()

            # Keep connection alive
            while transport.is_active():
                time.sleep(2)

        except Exception as e:
            print(f"⚠️ Baglanti koptu ({e}), 5 saniye sonra tekrar deneniyor...")
            time.sleep(5)

if __name__ == "__main__":
    main()
