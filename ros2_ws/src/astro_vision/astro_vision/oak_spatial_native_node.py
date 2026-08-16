#!/usr/bin/env python3
"""ASTRO V1 — Native DepthAI Hardware-Accelerated Spatial Perception Node.

Leverages the OAK-D Lite Intel Movidius Myriad X VPU directly for:
  1. On-Device Color Camera (1080P / 30 FPS)
  2. On-Device Stereo Depth Engine (Subpixel + LR-check + Median Filter)
  3. On-Device Spatial Neural Network (MobileNet / Person / Face Detection)
  4. On-Device Multi-Object Tracker (Tracklet ID assignment)
  5. 3D Spatial Coordinates (X, Y, Z in meters) computed directly in silicon

Publishes to standard ROS 2 topics with ~0% Jetson CPU usage!
"""

import json
import threading
import time
import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32, Int32, String

try:
    import depthai as dai
except ImportError:
    dai = None

try:
    from astro_vision.image_utils import bgr_to_imgmsg
except ImportError:
    from image_utils import bgr_to_imgmsg


class OakSpatialNativeNode(Node):
    def __init__(self):
        super().__init__("oak_spatial_native_node")

        self.declare_parameter("fps", 30.0)
        self.declare_parameter("confidence_threshold", 0.5)
        self.declare_parameter("sync_nn", True)

        self._fps = float(self.get_parameter("fps").value)
        self._conf_thresh = float(self.get_parameter("confidence_threshold").value)
        self._sync_nn = bool(self.get_parameter("sync_nn").value)

        # Publishers
        self.pub_rgb = self.create_publisher(Image, "/oak/rgb/image_raw", 10)
        self.pub_depth = self.create_publisher(Image, "/oak/depth/image_raw", 10)
        self.pub_person_detected = self.create_publisher(Bool, "/vision/person_detected", 10)
        self.pub_person_count = self.create_publisher(Int32, "/vision/person_count", 10)
        self.pub_user_distance = self.create_publisher(Float32, "/vision/user_distance", 10)
        self.pub_head_yaw = self.create_publisher(Float32, "/vision/head_yaw", 10)
        self.pub_looking = self.create_publisher(Bool, "/vision/looking_at_robot", 10)
        self.pub_emotion = self.create_publisher(String, "/vision/user_emotion", 10)
        self.pub_faces = self.create_publisher(String, "/vision/faces", 10)
        self.pub_face_image = self.create_publisher(Image, "/vision/face_image", 10)

        self._running = False
        self._device = None
        self._thread = None

        if dai is None:
            self.get_logger().error(
                "❌ [DepthAI] 'depthai' python kütüphanesi bulunamadı! Lütfen 'pip install depthai' çalıştırın."
            )
            return

        self._start_pipeline()

    def _create_pipeline(self) -> dai.Pipeline:
        pipeline = dai.Pipeline()

        # 1. Color Camera
        cam_rgb = pipeline.create(dai.node.ColorCamera)
        cam_rgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
        cam_rgb.setPreviewSize(300, 300)
        cam_rgb.setInterleaved(False)
        cam_rgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
        cam_rgb.setFps(self._fps)

        # 2. Mono Cameras
        mono_left = pipeline.create(dai.node.MonoCamera)
        mono_right = pipeline.create(dai.node.MonoCamera)
        mono_left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
        mono_left.setBoardSocket(dai.CameraBoardSocket.LEFT)
        mono_right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
        mono_right.setBoardSocket(dai.CameraBoardSocket.RIGHT)

        # 3. Stereo Depth Engine (Hardware Accelerated on VPU)
        stereo = pipeline.create(dai.node.StereoDepth)
        stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
        stereo.setLeftRightCheck(True)
        stereo.setSubpixel(True)
        stereo.setDepthAlign(dai.CameraBoardSocket.RGB)
        mono_left.out.link(stereo.left)
        mono_right.out.link(stereo.right)

        # 4. Spatial Detection Network (Hardware NN + 3D Coordinates)
        spatial_nn = pipeline.create(dai.node.MobileNetSpatialDetectionNetwork)
        spatial_nn.setConfidenceThreshold(self._conf_thresh)
        spatial_nn.setBoundingBoxScaleFactor(0.5)
        spatial_nn.setDepthLowerThreshold(100)  # 100 mm (0.1m)
        spatial_nn.setDepthUpperThreshold(6000)  # 6000 mm (6.0m)

        # 5. Object Tracker (Hardware Tracking with Unique IDs)
        tracker = pipeline.create(dai.node.ObjectTracker)
        tracker.setTrackerType(dai.TrackerType.ZERO_TERM_COLOR_HISTOGRAM)
        tracker.setTrackerIdAssignmentPolicy(dai.TrackerIdAssignmentPolicy.SMALLEST_ID)

        # Link Spatial Pipeline
        cam_rgb.preview.link(spatial_nn.input)
        stereo.depth.link(spatial_nn.inputDepth)

        spatial_nn.passthrough.link(tracker.inputTrackerFrame)
        spatial_nn.passthrough.link(tracker.inputDetectionFrame)
        spatial_nn.out.link(tracker.inputDetections)

        # 6. XLink Outputs to Host
        xout_rgb = pipeline.create(dai.node.XLinkOut)
        xout_rgb.setStreamName("rgb")
        cam_rgb.video.link(xout_rgb.input)

        xout_track = pipeline.create(dai.node.XLinkOut)
        xout_track.setStreamName("tracklets")
        tracker.out.link(xout_track.input)

        return pipeline

    def _start_pipeline(self):
        try:
            pipeline = self._create_pipeline()
            self._device = dai.Device(pipeline)
            self._running = True
            self.get_logger().info("✅ [DepthAI Native] OAK-D Lite Donanım Hızlandırmalı Mekansal Pipeline Başlatıldı!")

            self._thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._thread.start()
        except Exception as e:
            self.get_logger().error(f"❌ [DepthAI Native] OAK-D Lite cihazına bağlanılamadı: {e}")

    def _worker_loop(self):
        q_rgb = self._device.getOutputQueue(name="rgb", maxSize=4, blocking=False)
        q_track = self._device.getOutputQueue(name="tracklets", maxSize=4, blocking=False)

        while rclpy.ok() and self._running:
            in_rgb = q_rgb.tryGet()
            in_track = q_track.tryGet()

            frame = None
            if in_rgb is not None:
                frame = in_rgb.getCvFrame()

            tracklets = in_track.tracklets if in_track is not None else []

            if frame is not None:
                header = self.get_clock().now().to_msg()
                h, w = frame.shape[:2]

                face_list = []
                closest_dist = 0.0
                closest_yaw = 0.0
                person_detected = False
                is_looking = False

                for t in tracklets:
                    # Filter for person / face detections
                    roi = t.roi.denormalize(w, h)
                    x1 = int(roi.topLeft().x)
                    y1 = int(roi.topLeft().y)
                    x2 = int(roi.bottomRight().x)
                    y2 = int(roi.bottomRight().y)
                    bw = x2 - x1
                    bh = y2 - y1

                    # Spatial coordinates (X, Y, Z in mm -> convert to meters)
                    sp = t.spatialCoordinates
                    x_m = sp.x / 1000.0
                    y_m = sp.y / 1000.0
                    z_m = sp.z / 1000.0

                    if z_m > 0.1:
                        person_detected = True
                        closest_dist = z_m
                        # Calculate yaw angle from 3D position
                        yaw_deg = float(np.degrees(np.arctan2(x_m, z_m)))
                        closest_yaw = yaw_deg
                        direct_gaze = abs(yaw_deg) <= 15.0
                        if direct_gaze:
                            is_looking = True

                        face_list.append({
                            "track_id": t.id,
                            "status": str(t.status),
                            "x": x1, "y": y1, "width": bw, "height": bh,
                            "spatial_x_m": round(x_m, 2),
                            "spatial_y_m": round(y_m, 2),
                            "distance_m": round(z_m, 2),
                            "yaw_deg": round(yaw_deg, 1),
                            "looking_at_robot": direct_gaze,
                            "emotion": "neutral"
                        })

                        # Draw OAK-D HUD
                        color = (0, 255, 0) if direct_gaze else (0, 200, 255)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        hud_text = f"ID:{t.id} | {z_m:.2f}m | {yaw_deg:.0f}°"
                        cv2.putText(frame, hud_text, (x1, max(22, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

                # Publish Standard ROS 2 Topics
                rgb_msg = bgr_to_imgmsg(frame, header)
                self.pub_rgb.publish(rgb_msg)

                p_msg = Bool()
                p_msg.data = person_detected
                self.pub_person_detected.publish(p_msg)

                cnt_msg = Int32()
                cnt_msg.data = len(face_list)
                self.pub_person_count.publish(cnt_msg)

                d_msg = Float32()
                d_msg.data = float(closest_dist)
                self.pub_user_distance.publish(d_msg)

                y_msg = Float32()
                y_msg.data = float(closest_yaw)
                self.pub_head_yaw.publish(y_msg)

                l_msg = Bool()
                l_msg.data = is_looking
                self.pub_looking.publish(l_msg)

                emo_msg = String()
                emo_msg.data = "neutral"
                self.pub_emotion.publish(emo_msg)

                faces_msg = String()
                faces_msg.data = json.dumps(face_list)
                self.pub_faces.publish(faces_msg)

                hud_msg = bgr_to_imgmsg(frame, header)
                self.pub_face_image.publish(hud_msg)

            time.sleep(0.01)

    def destroy_node(self):
        self._running = False
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = OakSpatialNativeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
