import logging
import os
import cv2
import json

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore import pyqtSignal, pyqtSlot, Qt, QThread

from gui.data_classes import Frame, VideoSource
from gui.widgets.tabs import MainTab, DebugTab, VideoTab
from gui.logger import root_logger

from util import data_path

# The name of the logger will be included in debug messages, so set it to the name of the file to make the log traceable
logger = root_logger.getChild(__name__)


class VideoThread(QThread):
    update_frames_signal = pyqtSignal(Frame)

    def __init__(self, video_sources):
        super().__init__()
        self._thread_running_flag = True
        self._video_playing_flag = True
        self._restart = False

        self._video_sources = video_sources
        self._captures = []
        self._rewind = False

    def _prepare_captures(self):
        """Initialize video capturers from self._video_sources"""
        for source in self._video_sources:
            self._captures.append(cv2.VideoCapture(source.filename, source.api_preference))

    def _emit_frames(self):
        """Emit next/prev frames on the pyqtSignal to be received by video widgets"""

        # Restart the videos if restart is true
        if self._restart:
            for index, capture in enumerate(self._captures):
                capture.set(cv2.CAP_PROP_POS_FRAMES, 0)

            self._restart = False

        for index, capture in enumerate(self._captures):

            if self._rewind:
                prev_frame = cur_frame = capture.get(cv2.CAP_PROP_POS_FRAMES)

                if cur_frame >= 2:
                    # Go back 2 frames so when we read() we'll read back 1 frame
                    prev_frame -= 2
                else:
                    # If at beginning, just read 1st frame over and over
                    prev_frame = 0

                capture.set(cv2.CAP_PROP_POS_FRAMES, prev_frame)

            # Read the frame
            ret, cv_img = capture.read()
            if ret:
                self.update_frames_signal.emit(Frame(cv_img, index))

    def run(self):
        self._prepare_captures()

        # Run the play/pausable video
        while self._thread_running_flag:
            # Send frames if the video is playing
            if self._video_playing_flag:
                self._emit_frames()

            # Wait if playing normally, don't if rewinding b/c rewinding is slow
            if not self._rewind:
                self.msleep(int(1000 / 30))

        # Shut down capturers
        for capture in self._captures:
            capture.release()

    def next_frame(self):
        """Goes forward a frame if the video is paused"""
        if not self._video_playing_flag:
            prev_rewind_state = self._rewind
            self._rewind = False
            self._emit_frames()
            self._rewind = prev_rewind_state

    def prev_frame(self):
        """Goes back a frame if the video is paused"""
        if not self._video_playing_flag:
            prev_rewind_state = self._rewind
            self._rewind = True
            self._emit_frames()
            self._rewind = prev_rewind_state

    def toggle_rewind(self):
        """Toggles the video rewind flag"""
        self._rewind = not self._rewind

    def toggle_play_pause(self):
        """Toggles the video playing flag"""
        self._video_playing_flag = not self._video_playing_flag

    def stop(self):
        """Sets the video playing & thread running flags to False and waits for thread to end"""
        self._video_playing_flag = False
        self._thread_running_flag = False
        self.wait()

    def restart(self):
        """Restarts the video from the beginning"""

        self._restart = True

    @pyqtSlot(list)
    def on_select_filenames(self, filenames):
        """Adds all files specified in .json arrays or by selecting actual files"""

        self._video_sources = []

        for filename in filenames:
            if os.path.splitext(filename)[1] == ".json":
                file = open(filename, "r")
                json_data = json.load(file)

                if json_data["sources"]:
                    for source in json_data["sources"]:
                        api = cv2.CAP_FFMPEG
                        if source["api"] == "gstreamer":
                            api = cv2.CAP_GSTREAMER
                        else:
                            source["name"] = os.path.join(data_path, source["name"])
                        
                        self._video_sources.append(VideoSource(source["name"], api))

                file.close()
            else:
                self._video_sources.append(VideoSource(filename, cv2.CAP_FFMPEG))

        print(self._video_sources)

        self._video_playing_flag = True
        self._captures = []
        self._rewind = False
        self._prepare_captures()


class GuiLogHandler(logging.Handler):
    def __init__(self, update_signal):
        super().__init__()
        self.update_signal = update_signal

    def emit(self, record):
        self.update_signal.emit(self.format(record), record.levelno)


class App(QWidget):
    main_log_signal = pyqtSignal(str, int)
    debug_log_signal = pyqtSignal(str, int)

    def __init__(self, video_sources):
        super().__init__()
        self.setWindowTitle("ROV Vision")
        self.resize(1280, 720)
        # self.showFullScreen()

        # Create a tab widget
        self.tabs = QTabWidget()
        self.main_tab = MainTab(len(video_sources))
        self.debug_tab = DebugTab(len(video_sources))

        self.tabs.resize(300, 200)
        self.tabs.addTab(self.main_tab, "Main")
        self.tabs.addTab(self.debug_tab, "Debug")

        # Create a vbox to hold the tabs widget
        vbox = QVBoxLayout()
        vbox.addWidget(self.tabs)

        # Set the root layout to this vbox
        self.setLayout(vbox)

        # Set the vbox layout as the widgets layout
        self.setLayout(vbox)

        # Create the video capture thread
        self.thread = VideoThread(video_sources)

        # Connect its signal to the update_image slot
        self.thread.update_frames_signal.connect(self.update_image)

        # Connect DebugTab's selecting files signal to video thread's on_select_filenames
        self.debug_tab.select_files_signal.connect(self.thread.on_select_filenames)

        # Setup the debug video buttons to control the thread
        self.debug_tab.widgets.video_controls.play_pause_button.clicked.connect(self.thread.toggle_play_pause)
        self.debug_tab.widgets.video_controls.restart_button.clicked.connect(self.thread.restart)
        self.debug_tab.widgets.video_controls.toggle_rewind_button.clicked.connect(self.thread.toggle_rewind)
        self.debug_tab.widgets.video_controls.prev_frame_button.clicked.connect(self.thread.prev_frame)
        self.debug_tab.widgets.video_controls.next_frame_button.clicked.connect(self.thread.next_frame)

        # Start the thread
        self.thread.start()

        # Setup GUI logging
        gui_formatter = logging.Formatter("[{levelname}] {message}", style="{")

        self.main_log_handler = GuiLogHandler(self.main_log_signal)
        self.main_log_handler.setLevel(logging.INFO)
        self.main_log_handler.setFormatter(gui_formatter)
        root_logger.addHandler(self.main_log_handler)
        self.main_log_signal.connect(self.main_tab.update_console)

        self.debug_log_handler = GuiLogHandler(self.debug_log_signal)
        self.debug_log_handler.setLevel(logging.DEBUG)
        self.debug_log_handler.setFormatter(gui_formatter)
        root_logger.addHandler(self.debug_log_handler)
        self.debug_log_signal.connect(self.debug_tab.update_console)

        logger.debug("Application initialized")

    def keyPressEvent(self, event):
        """Sets keyboard keys to different actions"""

        if event.key() == Qt.Key.Key_Space:
            self.thread.toggle_play_pause()

        elif event.key() == Qt.Key.Key_Left:
            self.thread.prev_frame()

        elif event.key() == Qt.Key.Key_Right:
            self.thread.next_frame()

        elif event.key() == Qt.Key.Key_R:
            self.thread.restart()

        elif event.key() == Qt.Key.Key_T:
            self.thread.toggle_rewind()

    def closeEvent(self, event):
        self.thread.stop()
        event.accept()

    @pyqtSlot(Frame)
    def update_image(self, frame: Frame):
        """Updates the appropriate tab with a new opencv image"""

        # Update the tab which is currently being viewed only if it is a VideoTab
        current_tab = self.tabs.currentWidget()
        if isinstance(current_tab, VideoTab):
            current_tab.handle_frame(frame)
