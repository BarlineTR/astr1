#!/usr/bin/env python3
"""ASTRO V1 — Yüz algılama ve kişi tanıma düğümü.

Yayınlar:
  /vision/faces           (String) — JSON: her yüz için ad, benzerlik ve kutu
  /vision/person_detected (Bool)   — karede yüz var mı
  /vision/person_name     (String) — tanınan kişi ("" = kimse yok/tanınmadı)
  /vision/face_image      (Image)  — kutular ve isimler çizilmiş kare

Tanıma YuNet + SFace ile yapılır (bkz. face_db.py). Model dosyaları yoksa düğüm
ölmez: Haar cascade ile yalnızca *algılama* yaparak çalışmaya devam eder ve
isimlendirmeyi kapatır.

Kişi kaydı için: ./scripts/enroll_face.py
"""
import json
from collections import deque

import cv2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, String

try:
    from astro_vision.image_utils import bgr_to_imgmsg, imgmsg_to_bgr
except ImportError:
    from image_utils import bgr_to_imgmsg, imgmsg_to_bgr

try:
    from astro_vision.face_db import FaceEngine, FaceEngineUnavailable
except ImportError:
    from face_db import FaceEngine, FaceEngineUnavailable

UNKNOWN = "bilinmeyen"


class FaceDetectorNode(Node):
    def __init__(self):
        super().__init__("face_detector_node")
        self.declare_parameter("input_topic", "/oak/rgb/image_raw")
        self.declare_parameter("process_every_n", 3)
        self.declare_parameter("match_threshold", 0.363)
        self.declare_parameter("stable_frames", 3)
        # Haar yedeği için (yalnızca modeller yoksa kullanılır)
        self.declare_parameter("scale_factor", 1.1)
        self.declare_parameter("min_neighbors", 5)
        self.declare_parameter("min_size", 30)

        input_topic = self.get_parameter("input_topic").value
        self.process_every_n = max(1, int(self.get_parameter("process_every_n").value))
        self.stable_frames = max(1, int(self.get_parameter("stable_frames").value))

        # Tanıma motoru — yoksa yalnızca algılamaya düşülür
        self.engine = None
        self.face_cascade = None
        try:
            self.engine = FaceEngine(
                cosine_threshold=float(self.get_parameter("match_threshold").value)
            )
            self.get_logger().info(
                f"✅ [Yüz] Tanıma aktif — kayıtlı kişiler: {self.engine.summary()}"
            )
            if not self.engine.people:
                self.get_logger().warn(
                    "Kayıtlı kişi yok — herkes \"bilinmeyen\" görünecek. "
                    "Kayıt için: ./scripts/enroll_face.py --name <isim> --capture"
                )
        except FaceEngineUnavailable as exc:
            self.get_logger().error(f"⚠️  [Yüz] Tanıma kapalı — {exc}")
            self.get_logger().warn("Haar cascade ile yalnızca yüz ALGILAMA yapılacak (isim yok)")
            self._init_haar()

        self.pub_faces = self.create_publisher(String, "/vision/faces", 10)
        self.pub_person = self.create_publisher(Bool, "/vision/person_detected", 10)
        self.pub_name = self.create_publisher(String, "/vision/person_name", 10)
        self.pub_image = self.create_publisher(Image, "/vision/face_image", 10)

        self._frame_index = 0
        self._last_published_name = None
        # Tek karelik yanılmalar isim değiştirmesin: son N kareye bakıp çoğunluğu al.
        self._recent_names = deque(maxlen=self.stable_frames)

        self.sub = self.create_subscription(Image, input_topic, self.image_callback, 10)
        self.get_logger().info(f"👁️  [Yüz] Dinleniyor: {input_topic}")

    def _init_haar(self):
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.face_cascade = cv2.CascadeClassifier(cascade_path)
        if self.face_cascade.empty():
            self.get_logger().error(f"Haar cascade da yüklenemedi: {cascade_path}")
            self.face_cascade = None

    # ------------------------------------------------------------------
    def image_callback(self, msg: Image):
        self._frame_index += 1
        # Her kareyi işlemek gereksiz; robotun tepkisi için ~10 Hz fazlasıyla yeter.
        if self._frame_index % self.process_every_n:
            return

        try:
            frame = imgmsg_to_bgr(msg)
        except Exception as e:
            self.get_logger().warn(f"Görüntü dönüştürülemedi: {e}")
            return

        faces = self._detect_and_identify(frame)

        for face in faces:
            self._draw(frame, face)

        self.pub_faces.publish(String(data=json.dumps(faces, ensure_ascii=False)))
        self.pub_person.publish(Bool(data=len(faces) > 0))
        self._publish_name(faces)
        self.pub_image.publish(bgr_to_imgmsg(frame, msg.header))

    def _detect_and_identify(self, frame) -> list[dict]:
        if self.engine is None:
            return self._detect_haar(frame)

        results = []
        for row in self.engine.detect(frame):
            x, y, w, h = (int(v) for v in row[:4])
            name, score = self.engine.identify(self.engine.embed(frame, row))
            results.append({
                "name": name or UNKNOWN,
                "known": name is not None,
                "similarity": round(float(score), 3),
                "x": x, "y": y, "width": w, "height": h,
                "confidence": round(float(row[14]), 3),
            })
        return results

    def _detect_haar(self, frame) -> list[dict]:
        if self.face_cascade is None:
            return []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        boxes = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=float(self.get_parameter("scale_factor").value),
            minNeighbors=int(self.get_parameter("min_neighbors").value),
            minSize=(int(self.get_parameter("min_size").value),) * 2,
        )
        return [
            {"name": UNKNOWN, "known": False, "similarity": 0.0,
             "x": int(x), "y": int(y), "width": int(w), "height": int(h), "confidence": 1.0}
            for x, y, w, h in boxes
        ]

    def _draw(self, frame, face: dict):
        color = (0, 200, 0) if face["known"] else (0, 165, 255)
        x, y, w, h = face["x"], face["y"], face["width"], face["height"]
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        label = f"{face['name']} {face['similarity']:.2f}" if face["known"] else face["name"]
        cv2.putText(frame, label, (x, max(y - 8, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    def _publish_name(self, faces: list[dict]):
        """En büyük (en yakın) yüzün adını, birkaç kare oturduktan sonra yayınlar."""
        known = [f for f in faces if f["known"]]
        current = max(known, key=lambda f: f["width"] * f["height"])["name"] if known else ""
        self._recent_names.append(current)

        # Çoğunluk kararı: anlık yanlış eşleşme robotun ismi değiştirmesine yol açmasın.
        stable = max(set(self._recent_names), key=self._recent_names.count)
        if self._recent_names.count(stable) < len(self._recent_names):
            return
        if stable == self._last_published_name:
            return

        self._last_published_name = stable
        self.pub_name.publish(String(data=stable))
        if stable:
            self.get_logger().info(f"🙋 [Yüz] Tanındı: {stable}")
        else:
            self.get_logger().info("👤 [Yüz] Tanıdık kimse görünmüyor")


def main():
    rclpy.init()
    node = FaceDetectorNode()
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
