import sys
import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

local_file = sys.argv[1]
remote_file = sys.argv[2]
cmd = sys.argv[3]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.1.111", username="okistech", password="123456", timeout=10)

sftp = ssh.open_sftp()
sftp.put(local_file, remote_file)
sftp.close()

stdin, stdout, stderr = ssh.exec_command(cmd)
for line in iter(stdout.readline, ""):
    print(line, end="", flush=True)
err = stderr.read().decode("utf-8", errors="replace")
if err:
    print(err, file=sys.stderr, end="")
ssh.close()
