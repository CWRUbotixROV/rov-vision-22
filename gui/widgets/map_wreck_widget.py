
import subprocess
import os
import threading
from vision.transect.map_wreck import MapWreck

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PyQt5.QtCore import QThread, pyqtSlot, Qt
from logger import root_logger

logger = root_logger.getChild(__name__)

class MapWreckThread(QThread):

    def __init__(self):
        super().__init__()

    def run(self):
        logger.debug("Starting map wreck thread")
        self.mapper = MapWreck()
        self.mapper.show_canvas()
    
    @pyqtSlot(Qt.Key)
    def key_slot(self, key):
        if self.isRunning():
            self.mapper.key_press(key)

def run():
    logger.debug("Starting map wreck thread")
    mapper = MapWreck()
    mapper.show_canvas()

class MapWreckWidget(QWidget):

    def __init__(self):
        super().__init__()

        self.map_thread = MapWreckThread()
    
    def map_wreck(self):
        if not self.map_thread.isRunning():
            self.map_thread.start()