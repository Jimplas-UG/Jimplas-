#!/usr/bin/env python3
from pathlib import Path
import paramiko

script = Path(__file__).resolve().parents[2] / "deploy/ubuntu/build-apk-fra.sh"
# ensure LF
raw = script.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
script.write_bytes(raw)

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
sftp = c.open_sftp()
sftp.put(str(script), "/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh")
sftp.close()
CMD = r"""
sed -i 's/\r$//' /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
chmod +x /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
pkill -f build-apk-fra.sh || true
sleep 1
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh > /var/log/bilshenz/apk-build-nohup.out 2>&1 &
sleep 6
echo '--- nohup ---'
head -n 40 /var/log/bilshenz/apk-build-nohup.out || true
echo '--- log ---'
head -n 40 /var/log/bilshenz/apk-build.log || true
echo '--- procs ---'
ps -ef | grep -E 'build-apk-fra|npm|expo|gradle' | grep -v grep | head -10 || true
"""
_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode("ascii", "replace"))
print(e.read().decode("ascii", "replace")[-500:])
c.close()
