"""Shared helpers for resolving USB serial device paths on the robot."""
import glob
import os
from typing import Iterable, List, Optional


def resolve_serial_port(primary: str, fallbacks: Optional[Iterable[str]] = None) -> Optional[str]:
    """Return the first existing serial port from candidates, or None."""
    candidates: List[str] = [primary]
    if fallbacks:
        candidates.extend(fallbacks)

    for port in candidates:
        if port and os.path.exists(port):
            return port

    for pattern in ("/dev/astro_*", "/dev/ttyACM*", "/dev/ttyUSB*"):
        for port in sorted(glob.glob(pattern)):
            if os.path.exists(port):
                return port

    return None
