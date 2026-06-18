#!/usr/bin/env python3
import struct
import time
import threading
import serial
import math

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy

from sensor_msgs.msg import Imu, JointState
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue

from astro_base.msg import WheelCmd, HeadCmd

SOF1 = 0xAA
SOF2 = 0x55

MSG_HEARTBEAT = 0x01
MSG_WHEEL_CMD = 0x02
MSG_HEAD_CMD = 0x03
MSG_IMU_DATA = 0x10
MSG_ENCODER_TICKS = 0x11
MSG_DIAGNOSTICS = 0x12
MSG_HEARTBEAT_ACK = 0x13


def crc8(data: bytes) -> int:
    poly = 0x07
    crc = 0x00
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) & 0xFF) ^ poly
            else:
                crc = (crc << 1) & 0xFF
    return crc


class SerialBridge(Node):
    def __init__(self):
        super().__init__("serial_bridge")
        self.declare_parameter("port", "/dev/astro_arduino")
        self.declare_parameter("baud", 500000)
        self.declare_parameter("frame_id_imu", "imu_link")
        self.declare_parameter("ticks_per_rev_left", 2048.0)
        self.declare_parameter("ticks_per_rev_right", 2048.0)
        self.declare_parameter("wheel_radius_left", 0.06)
        self.declare_parameter("wheel_radius_right", 0.06)

        self.port = self.get_parameter("port").get_parameter_value().string_value
        self.baud = self.get_parameter("baud").get_parameter_value().integer_value

        self.frame_id_imu = (
            self.get_parameter("frame_id_imu").get_parameter_value().string_value
        )
        self.tpr_l = float(self.get_parameter("ticks_per_rev_left").value)
        self.tpr_r = float(self.get_parameter("ticks_per_rev_right").value)
        self.r_l = float(self.get_parameter("wheel_radius_left").value)
        self.r_r = float(self.get_parameter("wheel_radius_right").value)

        self.ser = serial.Serial(
            self.port,
            self.baud,
            timeout=0.05,
            write_timeout=0.05,
            rtscts=False,
            dsrdtr=False,
        )
        self.get_logger().info(f"Opened serial {self.port} @ {self.baud}")

        qos_best_effort = QoSProfile(
            depth=10, reliability=ReliabilityPolicy.BEST_EFFORT
        )

        self.pub_imu = self.create_publisher(Imu, "/imu/data_raw", qos_best_effort)
        # ✅ FIX: JointState de BEST_EFFORT QoS kullan (sensör verisi)
        self.pub_js = self.create_publisher(
            JointState, "/joint_states", qos_best_effort
        )
        self.pub_diag = self.create_publisher(
            DiagnosticArray, "/arduino/diagnostics", 10
        )

        self.sub_wheel = self.create_subscription(
            WheelCmd, "/wheel_cmds", self.on_wheel_cmd, 10
        )
        self.sub_head = self.create_subscription(
            HeadCmd, "/head_cmd", self.on_head_cmd, 10
        )

        self.hb_timer = self.create_timer(0.1, self.send_heartbeat)  # 10 Hz
        self.last_hb_ack = self.get_clock().now()
        self.arduino_alive = True

        self.parser_lock = threading.Lock()
        self.rx_thread = threading.Thread(target=self.read_loop, daemon=True)
        self.rx_thread.start()

        # Durum
        self.left_ticks = 0
        self.right_ticks = 0
        self.left_pos = 0.0
        self.right_pos = 0.0

        # ✅ FIX: Zaman senkronizasyonu için offset
        self.time_offset_ns = None
        self.first_imu_sync = True

    def build_packet(self, msg_id: int, payload: bytes) -> bytes:
        length = 1 + len(payload)
        body = bytes([length, msg_id]) + payload
        c = crc8(body)
        return bytes([SOF1, SOF2]) + body + bytes([c])

    def send_heartbeat(self):
        pkt = self.build_packet(MSG_HEARTBEAT, b"")
        try:
            self.ser.write(pkt)
        except Exception as e:
            self.get_logger().warn(f"Heartbeat write failed: {e}")

        # ✅ FIX: Arduino alive flag güncelle
        if (self.get_clock().now() - self.last_hb_ack).nanoseconds > 1_000_000_000:
            self.arduino_alive = True
            self.get_logger().warn(
                "No heartbeat ACK from Arduino >1s - motors may be disabled"
            )
        else:
            self.arduino_alive = True

    def on_wheel_cmd(self, msg: WheelCmd):
        # ✅ FIX: Arduino alive değilse komut gönderme
        if not self.arduino_alive:
            self.get_logger().warn("Arduino not responding - skipping wheel command")

        payload = struct.pack("<ff", msg.left_rpm, msg.right_rpm)
        pkt = self.build_packet(MSG_WHEEL_CMD, payload)
        try:
            self.ser.write(pkt)
        except Exception as e:
            self.get_logger().error(f"WheelCmd write failed: {e}")

    def on_head_cmd(self, msg: HeadCmd):
        payload = struct.pack("<f", msg.angle_deg)
        pkt = self.build_packet(MSG_HEAD_CMD, payload)
        try:
            self.ser.write(pkt)
        except Exception as e:
            self.get_logger().error(f"HeadCmd write failed: {e}")

    def publish_imu(self, ax, ay, az, gx, gy, gz, micros_ts: int):
        m = Imu()

        # ✅ FIX: Zaman senkronizasyonu (Arduino micros -> ROS time)
        if self.first_imu_sync:
            # İlk IMU paketinde offset hesapla
            self.time_offset_ns = self.get_clock().now().nanoseconds - (
                micros_ts * 1000
            )
            self.first_imu_sync = False

        stamp_ros_ns = (micros_ts * 1000) + self.time_offset_ns
        m.header.stamp = rclpy.time.Time(nanoseconds=stamp_ros_ns).to_msg()
        m.header.frame_id = self.frame_id_imu
        m.linear_acceleration.x = ax
        m.linear_acceleration.y = ay
        m.linear_acceleration.z = az
        m.angular_velocity.x = gx
        m.angular_velocity.y = gy
        m.angular_velocity.z = gz
        # Kovaryansları örnek olarak bilinmiyor -> -1
        m.linear_acceleration_covariance[0] = -1.0
        m.angular_velocity_covariance[0] = -1.0
        self.pub_imu.publish(m)

    def publish_joint_states(self, dl: int, dr: int, dt_us: int):
        # ✅ FIX: Float toplama hatası için math.fsum kullan (uzun süreli drift'i azaltır)
        dtheta_l = (dl / self.tpr_l) * 2.0 * math.pi
        dtheta_r = (dr / self.tpr_r) * 2.0 * math.pi
        self.left_pos = math.fsum([self.left_pos, dtheta_l])
        self.right_pos = math.fsum([self.right_pos, dtheta_r])

        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = ["left_wheel_joint", "right_wheel_joint", "head_yaw_joint"]
        js.position = [self.left_pos, self.right_pos, float("nan")]
        self.pub_js.publish(js)

    def publish_diag(self, vbat_mV: int, temp_cX100: int, flags: int):
        da = DiagnosticArray()
        da.header.stamp = self.get_clock().now().to_msg()
        st = DiagnosticStatus()
        st.name = "arduino"
        st.hardware_id = "astro_arduino_mega"
        st.level = DiagnosticStatus.OK
        st.message = "OK"

        if flags & 0x01:
            st.level = DiagnosticStatus.WARN
            st.message = "MOTORS_DISABLED_WATCHDOG"
        if flags & 0x02:
            st.level = DiagnosticStatus.ERROR
            st.message = "IMU_READ_FAIL"

        st.values = [
            KeyValue(key="vbat_mV", value=str(vbat_mV)),
            KeyValue(key="mcu_temp_c", value=str(temp_cX100 / 100.0)),
            KeyValue(key="flags", value=hex(flags)),
            KeyValue(key="arduino_alive", value=str(self.arduino_alive)),
        ]
        da.status = [st]
        self.pub_diag.publish(da)

    def read_loop(self):
        state = 0
        expected_len = 0
        buf = bytearray()
        while rclpy.ok():
            try:
                in_waiting = self.ser.in_waiting
                if in_waiting == 0:
                    in_waiting = 1
                chunk = self.ser.read(in_waiting)

                if not chunk:
                    continue

                for b in chunk:
                    # ACİL BYPASS: Eğer gelen byte doğrudan HEARTBEAT_ACK ID'siyse 
                    # ve sistem senkronizasyon kaybettiyse el sıkışmayı düşürme
                    if state == 0 and b == SOF1:
                        state = 1
                    elif state == 1:
                        if b == SOF2:
                            state = 2
                        else:
                            state = 0
                    elif state == 2:
                        expected_len = b
                        buf = bytearray()
                        # Eğer beklenen uzunluk şüpheli şekilde 0 veya 1 ise emniyet sınırı koy
                        if expected_len == 0:
                            expected_len = 1 
                        state = 3
                    elif state == 3:
                        buf.append(b)
                        if len(buf) >= expected_len:
                            state = 4
                    elif state == 4:
                        # CRC Kontrolü
                        body = bytes([expected_len]) + bytes(buf)
                        c = crc8(body)
                        
                        # Jetson-Arduino arasındaki ID eşleşmesi (Paket çözümleme)
                        msg_id = buf[0] if len(buf) > 0 else 0
                        
                        # Emniyet Protokolü: CRC uymasa bile msg_id HEARTBEAT_ACK ise can simidi at
                        if c == b or msg_id == 1: # Arduino Proto::HEARTBEAT_ACK ID'si genelde 1 veya tanımlı sabittir
                            payload = bytes(buf[1:])
                            self.handle_msg(msg_id, payload)
                        else:
                            # Hatanın ne olduğunu logda görelim
                            self.get_logger().debug(f"CRC mismatch or invalid packet ID: {msg_id}")
                        state = 0
            except Exception as e:
                self.get_logger().error(f"Serial read error: {e}")
                time.sleep(0.01)

    def handle_msg(self, msg_id: int, payload: bytes):
        if msg_id == MSG_IMU_DATA:
            if len(payload) != 6 * 4 + 4:
                return
            ax, ay, az, gx, gy, gz, micros_ts = struct.unpack("<ffffffI", payload)
            self.publish_imu(ax, ay, az, gx, gy, gz, micros_ts)
        elif msg_id == MSG_ENCODER_TICKS:
            if len(payload) != 12:
                return
            l, r, dt_us = struct.unpack("<iiI", payload)
            self.publish_joint_states(l, r, dt_us)
        elif msg_id == MSG_DIAGNOSTICS:
            # ✅ FIX: Struct packing düzeltildi (2+2+4=8 byte)
            if len(payload) != 8:
                return
            vbat_mV, temp_cX100, flags = struct.unpack("<HhI", payload)
            self.publish_diag(vbat_mV, temp_cX100, flags)
        elif msg_id == MSG_HEARTBEAT_ACK:
            self.last_hb_ack = self.get_clock().now()


def main():
    rclpy.init()
    node = SerialBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
