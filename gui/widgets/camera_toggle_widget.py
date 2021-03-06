from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PyQt5.QtCore import pyqtSignal

from vehicle.constants import Camera

from logger import root_logger

logger = root_logger.getChild(__name__)


class CameraToggleWidget(QWidget):
    set_cam_signal = pyqtSignal(Camera, bool)

    def __init__(self):
        super().__init__()
        self.root_layout = QHBoxLayout(self)
        self.setLayout(self.root_layout)

        self._buttons = {}

        for cam in Camera:
            button = QPushButton(cam.value, self)
            button.setCheckable(True)
            button.clicked.connect(self._create_slot(cam))
            self.root_layout.addWidget(button)
            self._buttons[cam] = button

        # Front and bottom cams start enabled
        for cam in (Camera.FRONT, Camera.BOTTOM):
            self._buttons[cam].setChecked(True)

    def _create_slot(self, camera: Camera):
        return lambda: self._emit_signal(camera)

    def _emit_signal(self, camera: Camera):
        self.set_cam_signal.emit(camera, self._buttons[camera].isChecked())

    def on_cameras_update(self, cam_dict: dict):
        for cam, val in cam_dict.items():
            self._buttons[cam].setChecked(val)
