#!/usr/bin/env python3
"""Rate and freshness tests for the webcam -> face detection path.

Face tracking was lagging by roughly a quarter second, and profiling showed the
cost was not detection: a loaded 640x480 frame costs ~13.5 ms on this class of CPU,
which would sustain ~74 Hz. The latency came from two throttles and a permanently
full driver buffer, so these tests pin the rates, the buffer depth and the cadence
plumbing rather than the detector's speed.
"""

import json
import os
import unittest

import cv2
import numpy as np

from astro_vision.face_detector_node import SpatialVisionNode
from astro_vision.webcam_publisher_node import WebcamPublisherNode


class _FakeCapture:
    """Records property writes the way cv2.VideoCapture applies them to V4L2."""

    def __init__(self, *_args, **_kwargs):
        self.props = {}
        self.released = False

    def isOpened(self):
        return True

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def get(self, prop):
        return self.props.get(prop, 0.0)

    def read(self):
        return True, np.zeros((480, 640, 3), np.uint8)

    def release(self):
        self.released = True


class TestWebcamPublisherKeepsFramesFresh(unittest.TestCase):
    """A 30 FPS camera polled at 15 Hz leaves every frame stale in the V4L2 queue.

    OpenCV buffers four frames by default, so the backlog never drains and read()
    returns in 0.26 ms with an image up to ~133 ms old — before detection starts.
    Consuming at the camera's own rate is what drains it; shrinking the queue is not.
    """

    def test_capture_runs_at_the_camera_rate_by_default(self):
        node = WebcamPublisherNode(capture_factory=_FakeCapture)

        self.assertEqual(node.fps, 30.0)

    def test_the_driver_queue_depth_is_left_alone(self):
        """Shrinking it to 1 was measured to cost a third of the frame rate on this
        camera (30 -> 20 FPS): the driver can no longer overlap DMA with userspace.
        Freshness comes from consuming at the camera's rate, not from a short queue.
        """
        node = WebcamPublisherNode(capture_factory=_FakeCapture)

        self.assertNotIn(cv2.CAP_PROP_BUFFERSIZE, node.cap.props)

    def test_the_requested_rate_is_pushed_down_to_the_driver(self):
        node = WebcamPublisherNode(capture_factory=_FakeCapture)

        self.assertEqual(node.cap.props[cv2.CAP_PROP_FPS], 30.0)


class TestFaceDetectorCadence(unittest.TestCase):
    def test_every_frame_is_processed_by_default(self):
        """The hardcoded `% 2` skip halved an already-halved stream down to 7.5 Hz."""
        node = SpatialVisionNode()

        self.assertEqual(node.process_every_n, 1)
        self.assertEqual([n for n in range(1, 7) if node._should_process(n)], [1, 2, 3, 4, 5, 6])

    def test_the_cadence_parameter_is_declared_so_the_config_can_reach_it(self):
        """camera_params.yaml sets process_every_n on a node that never declared it."""
        node = SpatialVisionNode()

        self.assertIn("process_every_n", node._declared_parameters)

    def test_a_configured_cadence_selects_every_nth_frame(self):
        node = SpatialVisionNode()
        node.process_every_n = 3

        self.assertEqual([n for n in range(1, 7) if node._should_process(n)], [3, 6])

    def test_the_declared_detector_tuning_reaches_the_cascade(self):
        """scale_factor / min_neighbors / min_size were read, then never used."""
        node = SpatialVisionNode()
        node.scale_factor, node.min_neighbors, node.min_size = 1.2, 7, 48

        self.assertEqual(
            node._face_detect_kwargs(),
            {"scaleFactor": 1.2, "minNeighbors": 7, "minSize": (48, 48)},
        )


class TestFallbackCascadeIsNotRunOnEveryEmptyFrame(unittest.TestCase):
    """The alt2 pass runs only when the first cascade finds nothing — which is most
    frames — and it is the single most expensive thing in the pipeline: 19.0 ms for
    the primary plus 13.6 ms for the fallback, against 6.8 ms when a face is present.
    """

    def test_the_fallback_is_rate_limited_rather_than_run_every_empty_frame(self):
        node = SpatialVisionNode()

        attempts = [n for n in range(1, 13) if node._should_try_fallback_cascade(n)]

        self.assertLess(len(attempts), 12, "the fallback must not run on every empty frame")
        self.assertGreater(len(attempts), 0, "the fallback must still get a chance to recover")


class TestAFrameFlowsThroughTheNode(unittest.TestCase):
    """Guards the plumbing the cadence work rewired: kwargs, skip test, publishing."""

    def _image_msg(self, frame):
        from astro_vision.face_detector_node import Image

        return Image(
            data=frame.tobytes(), height=frame.shape[0], width=frame.shape[1],
            encoding="bgr8", step=frame.shape[1] * 3, is_bigendian=0,
        )

    def test_a_processed_frame_publishes_a_face_list(self):
        node = SpatialVisionNode()
        frame = np.zeros((480, 640, 3), np.uint8)

        node.image_callback(self._image_msg(frame))

        self.assertIsNotNone(node.pub_faces.last_msg)
        self.assertEqual(json.loads(node.pub_faces.last_msg.data), [])

    def test_a_skipped_frame_publishes_nothing(self):
        node = SpatialVisionNode()
        node.process_every_n = 2
        frame = np.zeros((480, 640, 3), np.uint8)

        node.image_callback(self._image_msg(frame))

        self.assertIsNone(node.pub_faces.last_msg, "frame 1 of 2 must be skipped")


class TestConfigMatchesWhatTheNodesDeclare(unittest.TestCase):
    """camera_params.yaml was setting keys no node ever declared.

    ROS silently drops an override for an undeclared parameter, so the file read as
    documentation of behaviour that did not exist — process_every_n: 3 sat next to a
    hardcoded `% 2`, and nothing flagged the contradiction.
    """

    def _config(self) -> dict:
        import yaml

        path = os.path.join(
            os.path.dirname(__file__), "..", "config", "camera_params.yaml"
        )
        with open(path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def test_every_face_detector_key_is_declared_by_the_node(self):
        configured = set(self._config()["face_detector_node"]["ros__parameters"])
        declared = set(SpatialVisionNode()._declared_parameters)

        self.assertEqual(configured - declared, set())

    def test_every_webcam_key_is_declared_by_the_node(self):
        configured = set(self._config()["webcam_publisher_node"]["ros__parameters"])
        declared = set(WebcamPublisherNode(capture_factory=_FakeCapture)._declared_parameters)

        self.assertEqual(configured - declared, set())

    def test_the_configured_capture_rate_matches_the_camera(self):
        self.assertEqual(self._config()["webcam_publisher_node"]["ros__parameters"]["fps"], 30.0)

    def test_the_configured_cadence_processes_every_frame(self):
        self.assertEqual(
            self._config()["face_detector_node"]["ros__parameters"]["process_every_n"], 1
        )


if __name__ == "__main__":
    unittest.main()
