import os
import sys
import hashlib
import paramiko

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FILES_TO_SYNC = [
    ("ros2_ws/src/astro_ai/astro_ai/circuit_breaker.py", "/home/okistech/Desktop/astr1/ros2_ws/src/astro_ai/astro_ai/circuit_breaker.py"),
    ("ros2_ws/src/astro_ai/astro_ai/provider_registry.py", "/home/okistech/Desktop/astr1/ros2_ws/src/astro_ai/astro_ai/provider_registry.py"),
    ("ros2_ws/src/astro_base/astro_base/standalone_gaze_ros_node.py", "/home/okistech/Desktop/astr1/ros2_ws/src/astro_base/astro_base/standalone_gaze_ros_node.py"),
    ("ros2_ws/src/astro_ai/astro_ai/astro_realtime_node.py", "/home/okistech/Desktop/astr1/ros2_ws/src/astro_ai/astro_ai/astro_realtime_node.py"),
    ("ros2_ws/src/astro_audio/astro_audio/audio_stream_node.py", "/home/okistech/Desktop/astr1/ros2_ws/src/astro_audio/astro_audio/audio_stream_node.py"),
    (".env", "/home/okistech/Desktop/astr1/.env"),
    ("scripts/astro_web_agent.py", "/home/okistech/Desktop/astr1/scripts/astro_web_agent.py"),
    ("apps/site/src/app/api/kamera/route.ts", "/home/okistech/Desktop/astr1/apps/site/src/app/api/kamera/route.ts"),
    ("apps/site/src/app/api/lidar/route.ts", "/home/okistech/Desktop/astr1/apps/site/src/app/api/lidar/route.ts"),
    ("apps/site/src/app/panel/cihaz/[id]/page.tsx", "/home/okistech/Desktop/astr1/apps/site/src/app/panel/cihaz/[id]/page.tsx"),
    ("apps/site/src/components/KameraGorunumu.tsx", "/home/okistech/Desktop/astr1/apps/site/src/components/KameraGorunumu.tsx"),
    ("apps/site/src/components/LidarHarita.tsx", "/home/okistech/Desktop/astr1/apps/site/src/components/LidarHarita.tsx"),
    ("standalone/sources.py", "/home/okistech/Desktop/astr1/standalone/sources.py"),
    ("standalone/test/test_sources.py", "/home/okistech/Desktop/astr1/standalone/test/test_sources.py"),
    ("scripts/verify_4o_field_fixes.py", "/home/okistech/Desktop/astr1/scripts/verify_4o_field_fixes.py"),
    ("scripts/test_real_field.py", "/home/okistech/Desktop/astr1/scripts/test_real_field.py"),
]

def md5(fname):
    h = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

def sync():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("192.168.1.111", username="okistech", password="123456", timeout=10)
    sftp = ssh.open_sftp()

    for local, remote in FILES_TO_SYNC:
        if not os.path.exists(local):
            print(f"[ERROR] Local file does not exist: {local}")
            continue

        # ensure remote directory exists
        remote_dir = os.path.dirname(remote).replace("\\", "/")
        stdin, stdout, stderr = ssh.exec_command(f"mkdir -p '{remote_dir}'")
        stdout.read()

        print(f"Uploading {local} -> {remote} ...")
        with open(local, "rb") as f:
            content = f.read().replace(b"\r\n", b"\n")
        with sftp.file(remote, "wb") as rf:
            rf.write(content)

        # verify remote md5
        local_md5 = hashlib.md5(content).hexdigest()
        stdin, stdout, stderr = ssh.exec_command(f"md5sum '{remote}'")
        res = stdout.read().decode().strip()
        rem_md5 = res.split()[0] if res else ""
        if local_md5 == rem_md5:
            print(f"  ✅ Verified MD5: {rem_md5}")
        else:
            print(f"  ❌ MD5 MISMATCH: local={local_md5}, remote={rem_md5}")

    sftp.close()
    ssh.close()
    print("\nAll files synchronized successfully!")

if __name__ == "__main__":
    sync()
