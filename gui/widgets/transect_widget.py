import os
import cv2
import numpy as np

from vision.transect.stitch_transect import TransectStitcher
from vision.transect.transect_image import TransectImage
from vision.transect.stitch_pyqt import TransectStitcherWidget
from PyQt5.QtWidgets import QWidget, QPushButton, QHBoxLayout
from PyQt5.QtCore import QThread, pyqtSignal
from logger import root_logger
from util import data_path, undistort, BOTTOM_CAM_DIM, BOTTOM_CAM_K, BOTTOM_CAM_D

logger = root_logger.getChild(__name__)

class CaptureThread(QThread):

    image_to_save = None
    image_num = 0

    def __init__(self):
        super().__init__()

    def set_image(self, image, num):
        self.image_to_save = image
        self.image_num = num

    def run(self):
        corrected_image = undistort(self.image_to_save, BOTTOM_CAM_DIM, BOTTOM_CAM_K, BOTTOM_CAM_D, balance=1)

        file_name = f"transect_image({self.image_num}).png"
        path = os.path.join(data_path, "transect_frames", file_name)
        cv2.imwrite(path, corrected_image)

        logger.info(f"Saving {file_name} to {path}")

class TransectWidget(QWidget):
    stitched_image_signal = pyqtSignal(np.ndarray)

    picture_paths = []
    image_num = 0

    def __init__(self, app):
        super().__init__()

        self.app = app
        self.capture_thread = CaptureThread()

        # Horizontal layout
        self.root_layout = QHBoxLayout(self)
        self.setLayout(self.root_layout)

        # Creating the buttons
        self.capture_button = QPushButton("Capture Transect", self)
        self.capture_button.clicked.connect(self.capture)

        self.clear_button = QPushButton("Clear Previous", self)
        self.clear_button.clicked.connect(self.clear_previous)

        self.manual_button = QPushButton("Stitch Manually", self)
        self.manual_button.clicked.connect(self.stitch_manually)     

        self.root_layout.addWidget(self.capture_button)
        self.root_layout.addWidget(self.clear_button)
        self.root_layout.addWidget(self.manual_button)

        self.clear_directory()

    def clear_directory(self):
        dir = os.path.join(data_path, "transect_frames")

        for f in os.listdir(dir):
            os.remove(os.path.join(dir, f))

        self.image_num = 0

        logger.info("Cleared the transect_frames folder in the data repo")

    def clear_previous(self):
        if self.image_num != 0:
            prev_path = self.picture_paths.pop()

            os.remove(prev_path)
            self.image_num -= 1

            logger.info(f"Deleting transect frame {self.image_num+1}")
        else:
            logger.info("WARNING: There is no previous transect frame to delete")

    def capture(self):
        frame = self.app.get_active_frame().copy()

        self.image_num += 1

        self.capture_thread.set_image(frame, self.image_num)

        file_name = f"transect_image({self.image_num}).png"
        path = os.path.join(data_path, "transect_frames", file_name)

        self.picture_paths.append(path)

        if not self.capture_thread.isRunning():
            self.capture_thread.start()

    def stitch_manually(self):
        self.stitcher = TransectStitcher()
        self.transect_stitcher = TransectStitcherWidget(self.stitcher)
        self.transect_stitcher.stitched_image_signal.connect(lambda img: self.stitched_image_signal.emit(img))

        folder_path = os.path.join(data_path, "transect_frames")

        all_images = os.listdir(folder_path)
        all_images.sort()

        if len(all_images) == 8:
            for i in range(0, 8):
                image_path = os.path.join(folder_path, all_images[i])

                image = TransectImage(i, cv2.imread(image_path))
                self.stitcher.set_image(i, image)        

            self.transect_stitcher.initUI()
        else:
            logger.info(f"WARNING: Need 8 photos, {len(all_images)} were taken")