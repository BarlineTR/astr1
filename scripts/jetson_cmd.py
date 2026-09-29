import sys
import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def run(cmd):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("192.168.1.111", username="okistech", password="123456", timeout=10)
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    ssh.close()
    if out:
        print(out, end="")
    if err:
        print(err, file=sys.stderr, end="")

if __name__ == "__main__":
    run(sys.argv[1])
