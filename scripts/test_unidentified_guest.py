import os
import sys

sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_ai/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_ai")

import rclpy
from astro_ai.astro_realtime_node import AstroRealtimeNode

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def main():
    if not rclpy.ok():
        rclpy.init()
    os.environ["ASTRO_TEST_MODE"] = "1"
    node = AstroRealtimeNode()

    # 1. Unidentified resolution check
    ident = node.resolve_identities()
    print("Resolved session_identity:", ident["session_identity"])
    print("Resolved identity_source  :", ident["identity_source"])
    print("Resolved is_known         :", ident["is_known"])
    print("Resolved biometric_status :", ident["biometric_status"])

    # 2. Who am I query response for unknown person
    reply = node._generate_contextual_persona_fallback("ben kimim")
    print("Astro's reply to unknown person:", reply)

if __name__ == "__main__":
    main()
