import json
import typing as t
import time
import socket

from PyQt5.QtCore import pyqtSignal, pyqtSlot, QObject, QThreadPool
from pymavlink import mavutil

from logger import root_logger
from vehicle.constants import InputChannel, Relay, Camera

logger = root_logger.getChild(__name__)

TIMEOUT = 2  # Seconds without a message before we assume the connection's lost

BACKWARD_CAM_INDICES = (2,)

HOST = "192.168.2.2"  # The server's hostname or IP address
RELAY_SOCKET_PORT = 60000
CAMERA_SOCKET_PORT = 5000


class VehicleControl(QObject):
    connected_signal = pyqtSignal()
    disconnected_signal = pyqtSignal()
    armed_signal = pyqtSignal()
    disarmed_signal = pyqtSignal()
    mode_signal = pyqtSignal(str)
    set_mode_signal = pyqtSignal(str)
    cameras_set_signal = pyqtSignal(dict)
    depth_update_signal = pyqtSignal(float)

    def __init__(self, port):
        super().__init__()
        self.last_msg_time = None
        self.connected = False
        self.armed = False
        self.mode_id = None
        self.mode = None

        self.link = mavutil.mavlink_connection(f'udpin:0.0.0.0:{port}')

        self.camera_states = {cam: False for cam in Camera}
        self.camera_states[Camera.FRONT] = True
        self.camera_states[Camera.BOTTOM] = True

        self.set_mode_signal.connect(self.set_mode)

        self._thread_manager = QThreadPool()

    def update(self):
        msg = self.link.wait_heartbeat(blocking=False)
        if msg is not None:
            if not self.connected:
                self.connected_signal.emit()
                self.connected = True

            self.last_msg_time = time.time()
            msg_dict = msg.to_dict()

            armed = msg_dict.get("base_mode", None) & 0x80 == 0x80

            if armed != self.armed:
                if armed:
                    self.armed_signal.emit()
                    print('Try:', list(self.link.mode_mapping().keys()))
                else:
                    self.disarmed_signal.emit()
                self.armed = armed
            
            mode_id = msg_dict.get("custom_mode")
            if mode_id != self.mode_id:
                mode = None
                for m, m_id in self.link.mode_mapping().items():
                    if m_id == mode_id:
                        mode = m
                        break
                
                self.mode_id = mode_id
                self.mode = mode
                logger.info(f'New Mode: {mode}')
                self.mode_signal.emit(mode)

        else:
            if self.connected and time.time() - self.last_msg_time > TIMEOUT:
                self.disconnected_signal.emit()
                self.connected = False

        msg = self.link.recv_match(type="VFR_HUD", blocking=False)
        if msg is not None:
            self.depth_update_signal.emit(msg.alt)

    def arm(self) -> None:
        self.link.arducopter_arm()
        logger.info("Arm command sent")

    def disarm(self) -> None:
        self.turn_off_relays()
        self.link.arducopter_disarm()
        logger.info("Disarm command sent")

    def is_connected(self) -> bool:
        return self.connected

    def is_armed(self) -> bool:
        return self.armed

    def set_rc_input_pwms(self, pwms: t.Dict[int, int]) -> None:
        """Sets and RC input channel pwm value. PWM values should be between 1100 and 1900"""
        if not self.is_connected() or not self.is_armed():
            return

        rc_channel_values = [65535] * 18  # 65535 Means "ignore this field"

        for channel_id, pwm in pwms.items():
            if channel_id < 1 or channel_id > 18:
                raise ValueError(f"Channel id does not exist: {channel_id}")

            if not 1100 <= pwm <= 1900:
                raise ValueError(f"PWM values must be between 1100 and 1900, not f{pwm}")

            rc_channel_values[channel_id - 1] = pwm

        self.link.mav.rc_channels_override_send(
            self.link.target_system,  # target_system
            self.link.target_component,  # target_component
            *rc_channel_values  # RC channel list, in microseconds.
        )

    def set_rc_inputs(self, values: t.Dict[InputChannel, float]) -> None:
        """Sets inputs to the pixhawk using values between -1 (full reverse) and 1 (full forward)"""
        pwms = {}
        for channel, val in values.items():
            if not -1 <= val <= 1:
                raise ValueError(f"Inputs must be between -1 and 1, not {val}")

            pwm = round(val * 400 + 1500)
            pwm = min(max(pwm, 1100), 1900)  # Clamp to acceptable pwm range in case of float weirdness
            pwms[channel.value] = pwm

        self.set_rc_input_pwms(pwms)

    def stop_thrusters(self) -> None:
        self.set_rc_inputs({
            InputChannel.FORWARD: 0,
            InputChannel.LATERAL: 0,
            InputChannel.THROTTLE: 0,
            InputChannel.YAW: 0,
            InputChannel.PITCH: 0,
            InputChannel.ROLL: 0,
        })
        logger.debug("Thrusters stopped")
    
    @pyqtSlot(str)
    def set_mode(self, mode: str) -> None:
        logger.info(f'Setting mode: {mode}')
        if mode in self.link.mode_mapping():
            mode_id = self.link.mode_mapping()[mode]
            self.link.set_mode(mode_id)
        else:
            logger.info(f"Unknown mode: {mode}")

    def set_relay(self, relay: Relay, state: bool) -> None:
        if not self.is_connected() or (not self.is_armed() and state):
            return

        def task():
            logger.debug(f"Setting relay {relay.value} to {state}")

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                try:
                    sock.connect((HOST, RELAY_SOCKET_PORT))
                    sock.sendall(bytes([relay.value, int(state)]))
                except Exception as e:
                    logger.error(f'Exception in relay socket sending: {e}')
        
        self._thread_manager.start(task)

    def turn_off_relays(self) -> None:
        for relay in Relay:
            self.set_relay(relay, False)

    def set_camera_enabled(self, cam: Camera, enabled: bool) -> None:
        if not self.is_connected():
            return

        self.camera_states[cam] = enabled

        self.send_camera_state()

    def send_camera_state(self) -> None:
        cams_dict = {cam.value: val for cam, val in self.camera_states.items()}

        def task():
            logger.debug(f"Setting enabled cameras to {cams_dict}")

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                try:
                    sock.connect((HOST, CAMERA_SOCKET_PORT))
                    sock.sendall(bytes(json.dumps(cams_dict) + '\n', 'utf-8'))
                except Exception as e:
                    logger.error(f'Exception in camera socket sending: {e}')

        self.cameras_set_signal.emit(self.camera_states)
        self._thread_manager.start(task)

