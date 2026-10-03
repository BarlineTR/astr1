import sys
import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time

def run(cmd):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connected = False
    last_err = None
    for attempt in range(4):
        try:
            ssh.connect("192.168.1.111", username="okistech", password="123456", timeout=20, banner_timeout=20, auth_timeout=20)
            connected = True
            break
        except Exception as e:
            last_err = e
            time.sleep(2)
    if not connected:
        raise last_err
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    ssh.close()
    if out:
        print(out, end="")
    if err:
        print(err, file=sys.stderr, end="")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "-f" and len(sys.argv) > 2:
            with open(sys.argv[2], "r", encoding="utf-8") as f:
                cmd = f.read()
        elif sys.argv[1] == "-":
            cmd = sys.stdin.read()
        else:
            cmd = " ".join(sys.argv[1:])
    else:
        cmd = sys.stdin.read()
    run(cmd)
