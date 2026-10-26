"""Panel principal: qué grabar, cámara, sonido y el botón de grabar.

Sigue la idea de la ventana de Loom (todo en una columna, una sola decisión por
fila) con la forma y los colores del escritorio.
"""

from . import config, devices, screens, shortcuts, theme
from .preview import CameraPreview as CameraFeed
from .preview import MicLevel
from .qt import (
    QFrame, QHBoxLayout, QLabel, QPushButton, Qt, QTimer, QVBoxLayout, QWidget, pyqtSignal,
)
from .recorder import Request
from .widgets import (
    CameraPreview, Combo, CornerPicker, IconButton, LevelMeter, Segmented, Switch, label, row,
)

MODES = [("pantalla_camara", "Pantalla y cámara", ""), ("pantalla", "Pantalla", ""), ("camara", "Cámara", "")]
SOURCES = [("pantalla", "Pantalla", "monitor"), ("ventana", "Ventana", "window"), ("area", "Área", "area")]
QUALITIES = [("1080", "Full HD (1080p)"), ("720", "HD (720p)"), ("original", "Original")]


class Panel(QWidget):
    record_requested = pyqtSignal(object)   # Request
    library_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, settings: config.Settings):
        super().__init__()
        self.settings = settings
        self.cameras: list[devices.Device] = []
        self.mics: list[devices.Device] = []
        self.feed = CameraFeed(self)
        self.mic_level = MicLevel(self)
        self.wayland = config.session_type() == "wayland"
        self.drag_from = None
        t = theme.current()

        self.setWindowTitle(config.APP_NAME)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        surface = QFrame(self)
        surface.setObjectName("surface")
        outer.addWidget(surface)
        body = QVBoxLayout(surface)
        sp = t.shape.spacing
        body.setContentsMargins(18, 14, 18, 18)
        body.setSpacing(sp)

        # Cabecera: marca + biblioteca, ajustes y cerrar (al lado que use el escritorio).
        self.header = QWidget(surface)
        brand = QLabel(f"Rec<span style='color:{t.red.name()}'>ON</span>", self.header)
        brand.setObjectName("brand")
        brand.setTextFormat(Qt.TextFormat.RichText)
        self.library_btn = IconButton("library", "Biblioteca de grabaciones", parent=self.header)
        self.settings_btn = IconButton("gear", "Ajustes", parent=self.header)
        self.close_btn = IconButton("close", "Cerrar (Esc)", parent=self.header)
        if t.close_left:
            head = row(self.close_btn, 6, brand, None, self.library_btn, self.settings_btn, spacing=2)
        else:
            head = row(brand, None, self.library_btn, self.settings_btn, self.close_btn, spacing=2)
        self.header.setLayout(head)
        body.addWidget(self.header)

        # Modo y fuente.
        self.mode = Segmented(MODES, surface)
        body.addWidget(self.mode)
        self.source = Segmented(SOURCES, surface, compact=True)
        body.addWidget(self.source)
        self.source_detail = Combo(surface)
        body.addWidget(self.source_detail)
        self.source_hint = label("", "hint", surface)
        self.source_hint.setWordWrap(True)
        body.addWidget(self.source_hint)

        # Cámara.
        self.camera_card = QFrame(surface)
        self.camera_card.setObjectName("card")
        cam = QVBoxLayout(self.camera_card)
        cam.setContentsMargins(12, 10, 12, 12)
        cam.setSpacing(10)
        self.camera_icon = IconButton("camera", "Cámara", 30, 18, self.camera_card)
        self.camera_icon.setEnabled(False)
        self.camera_combo = Combo(self.camera_card)
        cam.addLayout(row(self.camera_icon, self.camera_combo))
        self.bubble_row = QWidget(self.camera_card)
        self.preview = CameraPreview(84, self.bubble_row)
        self.corner = CornerPicker(self.bubble_row)
        self.size = Segmented([("s", "S", ""), ("m", "M", ""), ("l", "L", "")], self.bubble_row, compact=True)
        self.size.setFixedWidth(118)
        self.mirror = Switch(self.bubble_row)
        self.mirror.setToolTip("Efecto espejo")
        controls = QVBoxLayout()
        controls.setSpacing(8)
        controls.addLayout(row(label("Esquina", "sub"), None, self.corner))
        controls.addLayout(row(label("Tamaño", "sub"), None, self.size))
        controls.addLayout(row(label("Espejo", "sub"), None, self.mirror))
        bubble_layout = QHBoxLayout(self.bubble_row)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(14)
        bubble_layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignVCenter)
        bubble_layout.addLayout(controls, 1)
        cam.addWidget(self.bubble_row)
        body.addWidget(self.camera_card)

        # Sonido.
        audio_card = QFrame(surface)
        audio_card.setObjectName("card")
        audio = QVBoxLayout(audio_card)
        audio.setContentsMargins(12, 10, 12, 12)
        audio.setSpacing(8)
        self.mic_icon = IconButton("mic", "Micrófono", 30, 18, audio_card)
        self.mic_icon.setEnabled(False)
        self.mic_combo = Combo(audio_card)
        audio.addLayout(row(self.mic_icon, self.mic_combo))
        self.meter = LevelMeter(audio_card)
        meter_row = row(38, self.meter)
        audio.addLayout(meter_row)
        self.system_audio = Switch(audio_card)
        speaker = IconButton("speaker", "", 30, 18, audio_card)
        speaker.setEnabled(False)
        audio.addLayout(row(speaker, label("Sonido del ordenador"), None, self.system_audio))
        body.addWidget(audio_card)

        # Calidad.
        self.quality = Combo(surface)
        for key, text in QUALITIES:
            self.quality.addItem(text, key)
        self.fps = Combo(surface)
        for fps in (30, 60):
            self.fps.addItem(f"{fps} fps", fps)
        self.fps.setFixedWidth(112)
        body.addLayout(row(self.quality, self.fps))

        self.record_btn = QPushButton("Empezar a grabar", surface)
        self.record_btn.setObjectName("record")
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        body.addSpacing(2)
        body.addWidget(self.record_btn)
        self.shortcut_hint = label("", "hint", surface)
        self.shortcut_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(self.shortcut_hint)

        self._load()
        self._connect()

    # --- ajustes guardados ---------------------------------------------------------

    def _load(self):
        s = self.settings
        self.mode.set_value(s["modo"])
        self.source.set_value(s["fuente"])
        self.corner.set_value(s["burbuja_posicion"])
        self.size.set_value(s["burbuja_tamano"])
        self.mirror.setChecked(s["camara_espejo"])
        self.system_audio.setChecked(s["audio_sistema"])
        self.quality.set_data(s["calidad"])
        self.fps.set_data(s["fps"])
        self._apply_mode()

    def _connect(self):
        self.close_btn.clicked.connect(self.hide)
        self.library_btn.clicked.connect(self.library_requested.emit)
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        self.mode.changed.connect(lambda v: (self.settings.set("modo", v), self._apply_mode()))
        self.source.changed.connect(lambda v: (self.settings.set("fuente", v), self._apply_mode()))
        self.corner.changed.connect(lambda v: self.settings.set("burbuja_posicion", v))
        self.size.changed.connect(lambda v: self.settings.set("burbuja_tamano", v))
        self.mirror.toggled.connect(self._mirror_changed)
        self.system_audio.toggled.connect(lambda v: self.settings.set("audio_sistema", v))
        self.quality.currentIndexChanged.connect(lambda _i: self.settings.set("calidad", self.quality.currentData()))
        self.fps.currentIndexChanged.connect(lambda _i: self.settings.set("fps", int(self.fps.currentData())))
        self.camera_combo.currentIndexChanged.connect(self._camera_changed)
        self.mic_combo.currentIndexChanged.connect(self._mic_changed)
        self.source_detail.currentIndexChanged.connect(self._detail_changed)
        self.record_btn.clicked.connect(self._record)
        self.feed.frame.connect(self.preview.set_image)
        self.feed.failed.connect(lambda msg: self.preview.set_image(None))
        self.mic_level.level.connect(self.meter.set_db)

    def _apply_mode(self):
        mode = self.mode.value
        uses_screen = mode != "camara"
        uses_camera = mode != "pantalla"
        self.source.setVisible(uses_screen)
        self.camera_card.setVisible(uses_camera)
        self._fill_source_detail()
        has_camera = bool(self.camera_combo.currentData())
        self.bubble_row.setVisible(uses_camera and has_camera and mode == "pantalla_camara")
        if self.isVisible():
            self._restart_camera()
        self._update_record_button()
        self.adjustSize()

    def _fill_source_detail(self):
        source = self.source.value
        uses_screen = self.mode.value != "camara"
        self.source_detail.blockSignals(True)
        self.source_detail.clear()
        hint = ""
        show_detail = False
        if uses_screen and not self.wayland:
            if source == "pantalla" and len(screens.QGuiApplication.screens()) > 1:
                for screen in screens.QGuiApplication.screens():
                    self.source_detail.addItem(screens.screen_label(screen), screen.name())
                self.source_detail.set_data(self.settings["monitor"]) or self.source_detail.set_data(
                    screens.screen_at_cursor().name())
                show_detail = True
            elif source == "ventana":
                self.source_detail.addItem("La ventana activa al empezar", 0)
                for xid, title in screens.x11_windows():
                    self.source_detail.addItem(title if len(title) < 52 else title[:50] + "…", xid)
                show_detail = True
        if uses_screen and source == "area":
            hint = "Al pulsar grabar, arrastra sobre la pantalla para marcar el área."
        elif uses_screen and self.wayland:
            hint = ("El escritorio te preguntará qué ventana compartir." if source == "ventana"
                    else "La primera vez, el escritorio te preguntará qué pantalla compartir.")
        self.source_detail.blockSignals(False)
        self.source_detail.setVisible(show_detail)
        self.source_hint.setText(hint)
        self.source_hint.setVisible(bool(hint))

    def _detail_changed(self, _index):
        if self.source.value == "pantalla" and isinstance(self.source_detail.currentData(), str):
            self.settings.set("monitor", self.source_detail.currentData())

    # --- dispositivos ---------------------------------------------------------------

    def refresh_devices(self):
        self.cameras = devices.cameras()
        self.mics = devices.microphones()
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        self.camera_combo.addItem("Sin cámara", "")
        for device in self.cameras:
            self.camera_combo.addItem(device.name, device.key)
        if not self.camera_combo.set_data(self.settings["camara"]):
            # La cámara guardada no está conectada: la primera que haya.
            self.camera_combo.setCurrentIndex(1 if self.cameras and self.settings["camara"] else 0)
        self.camera_combo.blockSignals(False)

        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        self.mic_combo.addItem("Sin micrófono", "")
        self.mic_combo.addItem("Micrófono predeterminado", devices.MIC_DEFAULT)
        for device in self.mics:
            self.mic_combo.addItem(device.name, device.key)
        if not self.mic_combo.set_data(self.settings["microfono"]):
            self.mic_combo.set_data(devices.MIC_DEFAULT)
        self.mic_combo.blockSignals(False)
        self._apply_mode()
        self._restart_mic()

    def _camera_changed(self, _index):
        self.settings.set("camara", self.camera_combo.currentData() or "")
        self._apply_mode()

    def _mic_changed(self, _index):
        self.settings.set("microfono", self.mic_combo.currentData() or "")
        self._restart_mic()
        self._update_record_button()

    def _mirror_changed(self, value: bool):
        self.settings.set("camara_espejo", value)
        self._restart_camera()

    def _restart_camera(self):
        key = self.camera_combo.currentData() or ""
        if self.isVisible() and key and self.mode.value != "pantalla":
            self.feed.start(devices.find(self.cameras, key), key, self.mirror.isChecked())
        else:
            self.feed.stop()
        has = bool(key)
        self.camera_icon.set_icon("camera" if has else "camera-off")

    def _restart_mic(self):
        key = self.mic_combo.currentData() or ""
        self.mic_icon.set_icon("mic" if key else "mic-off")
        self.meter.setVisible(bool(key))
        if self.isVisible() and key:
            self.mic_level.start(key)
        else:
            self.mic_level.stop()

    def _update_record_button(self):
        camera_only = self.mode.value == "camara"
        missing_camera = camera_only and not self.camera_combo.currentData()
        self.record_btn.setEnabled(not missing_camera)
        self.record_btn.setText("Elige una cámara" if missing_camera else "Empezar a grabar")

    # --- mostrar y grabar -------------------------------------------------------------

    def open(self):
        keys = shortcuts.current()
        self.shortcut_hint.setText(
            f"{shortcuts.label(keys['grabar'])} graba y detiene  ·  {shortcuts.label(keys['pausa'])} pausa")
        if not self.isVisible():
            screen = screens.screen_at_cursor().availableGeometry()
            self.adjustSize()
            self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self.refresh_devices)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not screens.composited():
            # Sin compositor (X11) las esquinas transparentes saldrían negras.
            from .qt import QPainterPath, QRectF, QRegion

            path = QPainterPath()
            radius = theme.current().shape.radius
            path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def hideEvent(self, event):
        self.feed.stop()
        self.mic_level.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self.cameras or self.mics:
            self._restart_camera()
            self._restart_mic()

    def build_request(self) -> Request:
        s = self.settings
        camera_key = self.camera_combo.currentData() or ""
        request = Request(
            mode=self.mode.value, source=self.source.value, camera_key=camera_key,
            camera=devices.find(self.cameras, camera_key), mic_key=self.mic_combo.currentData() or "",
            system_audio=self.system_audio.isChecked(), quality=self.quality.currentData(),
            fps=int(self.fps.currentData()), bubble_position=self.corner.value, bubble_size=self.size.value,
            mirror=self.mirror.isChecked(), denoise=s["reducir_ruido"], screen_name=s["monitor"],
        )
        if self.source.value == "ventana" and isinstance(self.source_detail.currentData(), int):
            request.window = int(self.source_detail.currentData())
        return request

    def _record(self):
        request = self.build_request()
        self.hide()
        self.record_requested.emit(request)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.record_btn.isEnabled():
            self._record()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # Se arrastra desde cualquier zona vacía (la ventana no tiene barra de título).
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None and hasattr(handle, "startSystemMove") and handle.startSystemMove():
                return
            from .qt import event_pos

            self.drag_from = event_pos(event)

    def mouseMoveEvent(self, event):
        if self.drag_from is not None:
            from .qt import global_pos

            self.move(global_pos(event) - self.drag_from)

    def mouseReleaseEvent(self, _event):
        self.drag_from = None

