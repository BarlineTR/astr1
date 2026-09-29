import re
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

log_path = r"C:\Users\erenb\.gemini\antigravity\brain\036a5a67-ad53-4f57-bfca-34977b5677f7\.system_generated\tasks\task-7836.log"

with open(log_path, "r", encoding="utf-8", errors="replace") as f:
    text = f.read()

accepted_events = []
rejected_events = []

for line in text.splitlines():
    if "ACCEPTED_SPEECH" in line:
        accepted_events.append(line.strip())
    elif "REJECTED_NOISE_BURST" in line:
        rejected_events.append(line.strip())

print(f"Total accepted (false_stt candidates): {len(accepted_events)}")
print(f"Total rejected bursts: {len(rejected_events)}")
print("\nFirst 10 accepted events:")
for ev in accepted_events[:10]:
    print(ev)
