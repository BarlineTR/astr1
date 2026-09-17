"""Image conversion without cv_bridge (avoids NumPy 2.x ABI issues on Jetson)."""
import array

import numpy as np
try:
    from sensor_msgs.msg import Image
except ImportError:
    class Image:
        pass


def imgmsg_to_bgr(msg: Image) -> np.ndarray:
    if msg.encoding == "bgr8":
        channels = 3
        data = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, channels)
        return data.copy()
    if msg.encoding == "rgb8":
        import cv2

        channels = 3
        data = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, channels)
        return cv2.cvtColor(data, cv2.COLOR_RGB2BGR)
    if msg.encoding in ("mono8", "8UC1"):
        data = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width)
        import cv2

        return cv2.cvtColor(data, cv2.COLOR_GRAY2BGR)
    raise ValueError(f"Unsupported image encoding: {msg.encoding}")


try:
    from std_msgs.msg import Header
except ImportError:
    class Header:
        pass


def bgr_to_imgmsg(frame: np.ndarray, header=None) -> Image:
    msg = Image()
    if not hasattr(msg, "header") or msg.header is None:
        msg.header = Header()

    if isinstance(header, Header) or header is not None:
        msg.header = header
    elif hasattr(header, "sec") and hasattr(header, "nanosec"):
        msg.header.stamp = header
        msg.header.frame_id = "oak_rgb_camera_optical_frame"
    else:
        msg.header.frame_id = "oak_rgb_camera_optical_frame"

    msg.height, msg.width = frame.shape[:2]
    msg.encoding = "bgr8"
    msg.is_bigendian = 0
    msg.step = int(frame.shape[1] * 3)
    msg.data = array.array("B", frame.tobytes())
    return msg
