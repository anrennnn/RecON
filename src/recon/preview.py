"""Vista previa de la cámara y nivel del micrófono mientras el panel está abierto.

Las imágenes se recogen desde el hilo principal con un temporizador
(try-pull-sample), así no hay que cruzar hilos con Qt.
"""

from . import devices
from .gst import Gst
from .qt import QImage, QObject, QTimer, pyqtSignal

PREVIEW_SIZE = 168


class CameraPreview(QObject):
    frame = pyqtSignal(object)  # QImage o None
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pipe = None
        self.sink = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._pull)

    def start(self, device, key: str, mirror: bool):
        self.stop()
        if Gst is None or not key:
            return
        flip = "videoflip method=horizontal-flip ! " if mirror else ""
        description = (
            f"{devices.camera_source(device, key)} ! videoconvert ! {flip}aspectratiocrop aspect-ratio=1/1 "
            f"! videoscale ! video/x-raw,format=RGB,width={PREVIEW_SIZE},height={PREVIEW_SIZE} "
            "! appsink name=sink max-buffers=1 drop=true sync=false"
        )
        try:
            self.pipe = Gst.parse_launch(description)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.sink = self.pipe.get_by_name("sink")
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        self.pipe.set_state(Gst.State.PLAYING)
        self.timer.start(40)

    def _on_error(self, _bus, message):
        error, _debug = message.parse_error()
        self.stop()
        self.failed.emit(error.message)

    def _pull(self):
        if self.sink is None:
            return
        sample = self.sink.emit("try-pull-sample", 0)
        if sample is None:
            return
        buffer = sample.get_buffer()
        ok, info = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return
        try:
            s = sample.get_caps().get_structure(0)
            width, height = s.get_value("width"), s.get_value("height")
            stride = len(info.data) // height if height else width * 3
            image = QImage(bytes(info.data), width, height, stride, QImage.Format.Format_RGB888).copy()
        finally:
            buffer.unmap(info)
        self.frame.emit(image)

    def stop(self):
        self.timer.stop()
        if self.pipe is not None:
            self.pipe.get_bus().remove_signal_watch()
            self.pipe.set_state(Gst.State.NULL)
            self.pipe = None
            self.sink = None
        self.frame.emit(None)


class MicLevel(QObject):
    level = pyqtSignal(float)  # dB (de -60 a 0)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pipe = None

    def start(self, key: str):
        self.stop()
        if Gst is None or not key:
            return
        description = (f"{devices.audio_source(key)} ! audioconvert ! level interval=60000000 post-messages=true "
                       "! fakesink sync=false")
        try:
            self.pipe = Gst.parse_launch(description)
        except Exception:  # noqa: BLE001
            self.pipe = None
            return
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::element", self._on_element)
        bus.connect("message::error", lambda *_: self.stop())
        self.pipe.set_state(Gst.State.PLAYING)

    def _on_element(self, _bus, message):
        s = message.get_structure()
        if s is None or s.get_name() != "level":
            return
        rms = s.get_value("rms")
        if rms:
            self.level.emit(max(rms))

    def stop(self):
        if self.pipe is not None:
            self.pipe.get_bus().remove_signal_watch()
            self.pipe.set_state(Gst.State.NULL)
            self.pipe = None
            self.level.emit(-90.0)
