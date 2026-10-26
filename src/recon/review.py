"""Ventana de revisión: aparece al terminar de grabar y desde la biblioteca.

Todo lo que se suele hacer con un vídeo recién grabado, a un clic: copiarlo para
pegarlo en un chat (o arrastrarlo), ponerle nombre, recortar el principio y el
final, quitar los silencios, transcribirlo y exportarlo para WhatsApp o correo.
"""

from datetime import datetime
from pathlib import Path

from . import config, files, icons, processing, theme, transcribe
from .jobs import probe
from .qt import (
    QDrag, QFrame, QImage, QLabel, QLineEdit, QMenu, QPainter, QPen, QPixmap, QPointF, QProgressBar, QPushButton,
    QRectF, QSize, Qt, QTextEdit, QTimer, QVBoxLayout, QWidget, event_pos, pyqtSignal,
)
from .widgets import Switch, label, rounded_pixmap, row

THUMB_W, THUMB_H = 524, 295


def _icon_button(text: str, icon_name: str, name: str = "") -> QPushButton:
    button = QPushButton(text)
    if name:
        button.setObjectName(name)
    color = theme.current().accent_text if name == "primary" else theme.current().text
    if name == "danger":
        color = theme.current().red
    button.setIcon(icons.icon(icon_name, color, 18))
    button.setIconSize(QSize(18, 18))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class Thumbnail(QWidget):
    """Miniatura del vídeo: clic para verlo, arrastrar para soltarlo en un chat o carpeta."""

    play = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(THUMB_W, THUMB_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clic para verlo · Arrástralo a un chat o a una carpeta")
        self.pixmap: QPixmap | None = None
        self.duration = ""
        self.path: Path | None = None
        self.press = None
        self.hover = False

    def set_video(self, path: Path, image: QImage, duration: str):
        self.path = path
        self.duration = duration
        self.pixmap = rounded_pixmap(image, THUMB_W, THUMB_H, theme.current().shape.control + 4)
        self.update()

    def enterEvent(self, _event):
        self.hover = True
        self.update()

    def leaveEvent(self, _event):
        self.hover = False
        self.update()

    def mousePressEvent(self, event):
        self.press = event_pos(event)

    def mouseMoveEvent(self, event):
        if self.press is None or self.path is None:
            return
        if (event_pos(event) - self.press).manhattanLength() < 12:
            return
        self.press = None
        drag = QDrag(self)
        drag.setMimeData(files.mime_for([self.path]))
        if self.pixmap is not None:
            drag.setPixmap(self.pixmap.scaledToWidth(200, Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, _event):
        if self.press is not None:
            self.play.emit()
        self.press = None

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.pixmap is not None:
            painter.drawPixmap(0, 0, self.pixmap)
        center = QPointF(self.width() / 2, self.height() / 2)
        r = 30 if self.hover else 27
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.GlobalColor.black if self.hover else Qt.GlobalColor.darkGray)
        painter.setOpacity(0.62)
        painter.drawEllipse(center, r, r)
        painter.setOpacity(1.0)
        icons.paint(painter, "play", QRectF(center.x() - 13, center.y() - 13, 28, 28), Qt.GlobalColor.white)
        if self.duration:
            fm = painter.fontMetrics()
            w = fm.horizontalAdvance(self.duration) + 14
            chip = QRectF(self.width() - w - 10, self.height() - 30, w, 22)
            painter.setBrush(Qt.GlobalColor.black)
            painter.setOpacity(0.7)
            painter.drawRoundedRect(chip, 6, 6)
            painter.setOpacity(1.0)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), self.duration)
        painter.end()


class RangeSlider(QWidget):
    """Línea de tiempo con dos asas: inicio y final del recorte."""

    changed = pyqtSignal(float, float, str)  # inicio, final, asa movida ("start"/"end")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration = 1.0
        self.start = 0.0
        self.end = 1.0
        self.dragging = ""
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_duration(self, duration: float):
        self.duration = max(duration, 0.1)
        self.start, self.end = 0.0, self.duration
        self.update()

    def _x(self, t: float) -> float:
        return 10 + (self.width() - 20) * t / self.duration

    def _t(self, x: float) -> float:
        return max(0.0, min(self.duration, (x - 10) / max(self.width() - 20, 1) * self.duration))

    def mousePressEvent(self, event):
        x = event_pos(event).x()
        self.dragging = "start" if abs(x - self._x(self.start)) <= abs(x - self._x(self.end)) else "end"
        self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event):
        if not self.dragging:
            return
        t = self._t(event_pos(event).x())
        gap = min(0.5, self.duration / 4)
        if self.dragging == "start":
            self.start = min(t, self.end - gap)
        else:
            self.end = max(t, self.start + gap)
        self.update()
        self.changed.emit(self.start, self.end, self.dragging)

    def mouseReleaseEvent(self, _event):
        self.dragging = ""

    def paintEvent(self, _event):
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(t.button)
        painter.drawRoundedRect(QRectF(10, y - 4, self.width() - 20, 8), 4, 4)
        a, b = self._x(self.start), self._x(self.end)
        painter.setBrush(t.accent)
        painter.drawRoundedRect(QRectF(a, y - 4, b - a, 8), 4, 4)
        for x in (a, b):
            painter.setPen(QPen(t.accent, 2))
            painter.setBrush(t.field)
            painter.drawRoundedRect(QRectF(x - 6, y - 13, 12, 26), 5, 5)
        painter.end()


class ReviewWindow(QWidget):
    changed = pyqtSignal()           # el vídeo cambió (nombre, recorte, borrado): refrescar la biblioteca
    library_requested = pyqtSignal()

    def __init__(self, settings: config.Settings, notify):
        super().__init__()
        self.settings = settings
        self.notify = notify
        self.path: Path | None = None
        self.info: dict = {}
        self.job = None
        t = theme.current()
        self.setWindowTitle("Revisar grabación · RecON")
        self.setObjectName("window")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        body = QVBoxLayout(self)
        body.setContentsMargins(20, 18, 20, 18)
        body.setSpacing(t.shape.spacing)

        self.thumb = Thumbnail(self)
        body.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = QLineEdit(self)
        self.title.setObjectName("titleEdit")
        self.title.setToolTip("Nombre del vídeo (pulsa Intro para guardarlo)")
        body.addWidget(self.title)
        self.meta = label("", "sub", self)
        body.addLayout(row(6, self.meta))

        # Acciones principales.
        self.copy_btn = _icon_button("Copiar", "copy", "primary")
        self.copy_btn.setToolTip("Copia el vídeo para pegarlo en un chat, un correo o una carpeta")
        self.folder_btn = _icon_button("Mostrar", "folder")
        self.export_btn = _icon_button("Exportar…", "export")
        self.export_menu = QMenu(self)
        self.export_btn.setMenu(self.export_menu)
        body.addLayout(row(self.copy_btn, self.folder_btn, self.export_btn, None))

        # Herramientas.
        self.tools = QFrame(self)
        self.tools.setObjectName("card")
        tools = QVBoxLayout(self.tools)
        tools.setContentsMargins(6, 6, 6, 6)
        tools.setSpacing(2)
        self.trim_btn = _icon_button("Recortar principio y final", "scissors", "flat")
        self.silence_btn = _icon_button("Quitar silencios y pausas", "silence", "flat")
        self.transcribe_btn = _icon_button("Transcribir y crear subtítulos", "text", "flat")
        for button in (self.trim_btn, self.silence_btn, self.transcribe_btn):
            button.setStyleSheet("text-align: left; padding-left: 12px;")
            tools.addWidget(button)
        body.addWidget(self.tools)

        # Recorte (sustituye a las herramientas mientras se usa).
        self.trimmer = QFrame(self)
        self.trimmer.setObjectName("card")
        trim = QVBoxLayout(self.trimmer)
        trim.setContentsMargins(14, 12, 14, 12)
        trim.setSpacing(8)
        self.frame = QLabel(self.trimmer)
        self.frame.setFixedSize(320, 180)
        self.frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        trim.addWidget(self.frame, 0, Qt.AlignmentFlag.AlignHCenter)
        self.range = RangeSlider(self.trimmer)
        trim.addWidget(self.range)
        self.range_label = label("", "sub", self.trimmer)
        self.replace_switch = Switch(self.trimmer)
        self.replace_switch.setChecked(True)
        trim.addLayout(row(self.range_label, None, label("Sustituir el original", "sub"), self.replace_switch))
        self.trim_cancel = QPushButton("Cancelar", self.trimmer)
        self.trim_save = QPushButton("Guardar recorte", self.trimmer)
        self.trim_save.setObjectName("primary")
        trim.addLayout(row(None, self.trim_cancel, self.trim_save))
        self.trimmer.hide()
        body.addWidget(self.trimmer)
        self.frame_timer = QTimer(self)
        self.frame_timer.setSingleShot(True)
        self.frame_timer.timeout.connect(self._load_frame)
        self.frame_at = 0.0

        # Tarea en curso.
        self.job_box = QWidget(self)
        job = QVBoxLayout(self.job_box)
        job.setContentsMargins(0, 0, 0, 0)
        job.setSpacing(6)
        self.job_label = label("", "sub", self.job_box)
        self.job_cancel = QPushButton("Cancelar", self.job_box)
        self.job_cancel.setObjectName("flat")
        self.job_bar = QProgressBar(self.job_box)
        self.job_bar.setRange(0, 1000)
        job.addLayout(row(self.job_label, None, self.job_cancel))
        job.addWidget(self.job_bar)
        self.job_box.hide()
        body.addWidget(self.job_box)

        # Mensaje del resultado (con acción opcional).
        self.result = label("", "sub", self)
        self.result.setWordWrap(True)
        self.result.hide()
        body.addWidget(self.result)

        # Transcripción.
        self.text_box = QFrame(self)
        text = QVBoxLayout(self.text_box)
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(6)
        self.text = QTextEdit(self.text_box)
        self.text.setReadOnly(True)
        self.text.setFixedHeight(120)
        self.copy_text_btn = QPushButton("Copiar texto", self.text_box)
        self.title_btn = QPushButton("Usar como nombre", self.text_box)
        self.title_btn.setObjectName("flat")
        text.addLayout(row(label("Transcripción", "section"), None, self.title_btn, self.copy_text_btn))
        text.addWidget(self.text)
        self.text_box.hide()
        body.addWidget(self.text_box)

        body.addStretch(1)
        self.delete_btn = _icon_button("Borrar", "trash", "danger")
        self.delete_btn.setToolTip("Mover a la papelera")
        self.library_btn = QPushButton("Biblioteca", self)
        self.done_btn = QPushButton("Listo", self)
        body.addLayout(row(self.delete_btn, None, self.library_btn, self.done_btn))

        self._connect()
        self.setFixedWidth(THUMB_W + 40)

    def _connect(self):
        self.thumb.play.connect(lambda: self.path and files.open_file(self.path))
        self.title.editingFinished.connect(self._rename)
        self.copy_btn.clicked.connect(self._copy)
        self.folder_btn.clicked.connect(lambda: self.path and files.show_in_folder(self.path))
        self.export_menu.aboutToShow.connect(self._fill_export)
        self.trim_btn.clicked.connect(self._open_trim)
        self.silence_btn.clicked.connect(self._remove_silences)
        self.transcribe_btn.clicked.connect(self._transcribe)
        self.trim_cancel.clicked.connect(self._close_trim)
        self.trim_save.clicked.connect(self._save_trim)
        self.range.changed.connect(self._range_changed)
        self.job_cancel.clicked.connect(lambda: self.job and self.job.cancel())
        self.copy_text_btn.clicked.connect(lambda: (files.copy_text(self.text.toPlainText()),
                                                    self._say("Texto copiado.")))
        self.title_btn.clicked.connect(self._use_title)
        self.delete_btn.clicked.connect(self._delete)
        self.library_btn.clicked.connect(self.library_requested.emit)
        self.done_btn.clicked.connect(self.close)

    # --- cargar ------------------------------------------------------------------

    def open_video(self, path: Path, fresh: bool = False):
        self.load(path)
        self._close_trim()
        self.result.hide()
        if fresh:
            self._say("Grabación guardada. Cópiala o arrástrala a donde quieras compartirla.")
        self.show()
        self.raise_()
        self.activateWindow()
        self.copy_btn.setFocus()

    def load(self, path: Path):
        self.path = path
        self.info = probe(path)
        thumb = config.THUMBS_DIR / f"revision-{abs(hash(str(path)))}.jpg"
        at = min(1.0, self.info["duration"] / 3)
        image = QImage()
        if processing.thumbnail(path, thumb, at, 1048):
            image = QImage(str(thumb))
            thumb.unlink(missing_ok=True)
        self.thumb.set_video(path, image, processing.format_duration(self.info["duration"]))
        self.title.setText(path.stem)
        self.title.setCursorPosition(0)
        created = datetime.fromtimestamp(path.stat().st_mtime)
        size = f"{self.info['width']}×{self.info['height']}" if self.info["width"] else ""
        parts = [processing.format_duration(self.info["duration"]), processing.format_size(self.info["size"]),
                 size, created.strftime("%d/%m/%Y %H:%M")]
        self.meta.setText("  ·  ".join(p for p in parts if p))
        self.silence_btn.setEnabled(self.info["audio"])
        self.silence_btn.setToolTip("" if self.info["audio"] else "El vídeo no tiene sonido.")
        self.transcribe_btn.setEnabled(self.info["audio"])
        self._show_transcript()

    def _show_transcript(self):
        text = transcribe.transcript(self.path) if self.path else ""
        self.text_box.setVisible(bool(text.strip()))
        self.text.setPlainText(text.strip())
        has = bool(text.strip())
        self.transcribe_btn.setText("Volver a transcribir" if has else "Transcribir y crear subtítulos")
        suggestion = transcribe.suggested_title(text) if has else ""
        self.title_btn.setVisible(bool(suggestion) and suggestion != (self.path.stem if self.path else ""))
        self.title_btn.setToolTip(suggestion)
        self.adjustSize()

    def _say(self, text: str, error: bool = False):
        self.result.setObjectName("error" if error else "sub")
        self.result.setStyleSheet("")  # vuelve a aplicar la hoja de estilos con el nombre nuevo
        self.result.setText(text)
        self.result.setVisible(bool(text))

    # --- acciones -------------------------------------------------------------------

    def _rename(self):
        if not self.path or self.title.text().strip() in ("", self.path.stem):
            self.title.setText(self.path.stem if self.path else "")
            return
        try:
            self.path = files.rename(self.path, self.title.text().strip())
        except OSError as exc:
            self._say(f"No se pudo cambiar el nombre: {exc}", True)
            return
        self.title.setText(self.path.stem)
        self.thumb.path = self.path
        self.changed.emit()

    def _copy(self):
        if self.path:
            files.copy_to_clipboard([self.path])
            self._say("Copiado. Pégalo en un chat, un correo o una carpeta (Ctrl+V).")

    def _fill_export(self):
        self.export_menu.clear()
        has_srt = bool(self.path and self.path.with_suffix(".srt").exists())
        for key, (text, _label) in processing.PRESETS.items():
            if key == "subtitulos" and not has_srt:
                continue
            if key in ("audio",) and not self.info.get("audio"):
                continue
            action = self.export_menu.addAction(text)
            action.triggered.connect(lambda _c=False, k=key: self._export(k))
        if self.info.get("duration", 0) > 60:
            for action in self.export_menu.actions():
                if action.text() == processing.PRESETS["gif"][0]:
                    action.setText(action.text() + " (mejor para vídeos cortos)")

    def _export(self, preset: str):
        try:
            job, out = processing.export(self.path, preset, self)
        except (FileNotFoundError, KeyError) as exc:
            self._say(str(exc), True)
            return

        def success():
            files.copy_to_clipboard([out])
            size = processing.format_size(out.stat().st_size)
            return f"Listo: «{out.name}» ({size}). Ya está copiado para pegarlo."

        job.on_success = success
        self._run(job)

    def _open_trim(self):
        if not self.path:
            return
        self.range.set_duration(self.info["duration"])
        self._range_changed(0.0, self.info["duration"], "start")
        self.tools.hide()
        self.trimmer.show()
        self.adjustSize()

    def _close_trim(self):
        self.trimmer.hide()
        self.tools.show()
        self.adjustSize()

    def _range_changed(self, start: float, end: float, handle: str):
        f = processing.format_duration
        self.range_label.setText(f"{f(start)} → {f(end)}   ({f(end - start)})")
        self.frame_at = start if handle == "start" else end
        self.frame_timer.start(120)

    def _load_frame(self):
        data = processing.frame_at(self.path, self.frame_at, 640)
        image = QImage.fromData(data, "PNG") if data else QImage()
        if not image.isNull():
            self.frame.setPixmap(rounded_pixmap(image, 320, 180, 8))

    def _save_trim(self):
        start, end = self.range.start, self.range.end
        if start < 0.05 and end > self.info["duration"] - 0.05:
            self._close_trim()
            return
        replace = self.replace_switch.isChecked()
        out = processing.sibling(self.path, "recortado")
        original = self.path

        def success():
            final = files.replace(original, out) if replace else out
            self.load(final)
            self.changed.emit()
            return "Recorte guardado." + (" El original está en la papelera." if replace else "")

        self._close_trim()
        self._run(processing.trim(self.path, start, end, out, self, success))

    def _remove_silences(self):
        out = processing.sibling(self.path, "sin silencios")
        original = self.path

        def success():
            final = files.replace(original, out)
            self.load(final)
            self.changed.emit()
            return ""

        job = processing.remove_silences(self.path, out, parent=self, on_success=success)
        job.finished.connect(lambda ok, msg: ok and self._say(msg + " El original está en la papelera."))
        self._run(job, say_result=False)

    def _transcribe(self):
        if not transcribe.is_ready():
            self._say("La transcripción funciona sin internet, pero hay que instalarla una vez "
                      "(unos 300 MB). Hazlo en Ajustes → Transcripción.", True)
            return
        job = transcribe.transcribe_job(self.path, self.settings["modelo_transcripcion"],
                                        self.settings["idioma_transcripcion"], self)
        step = job.steps[0]

        def status(line: str):
            if line.startswith("ESTADO "):
                self.job_label.setText(line[7:])

        step.on_output = status

        def success():
            self._show_transcript()
            self.changed.emit()
            return "Transcripción lista. Los subtítulos (.srt) están junto al vídeo."

        job.on_success = success
        self._run(job)

    def _use_title(self):
        suggestion = self.title_btn.toolTip()
        if suggestion:
            self.title.setText(suggestion)
            self._rename()
            self.title_btn.hide()

    def _delete(self):
        if not self.path:
            return
        if self.delete_btn.text() != "¿Seguro?":
            self.delete_btn.setText("¿Seguro?")
            QTimer.singleShot(3000, lambda: self.delete_btn.setText("Borrar"))
            return
        if files.trash(self.path):
            self.notify("Grabación movida a la papelera.")
            self.changed.emit()
            self.path = None
            self.close()
        else:
            self._say("No se pudo mover a la papelera.", True)

    # --- tareas ---------------------------------------------------------------------

    def _run(self, job, say_result: bool = True):
        if self.job is not None:
            self._say("Espera a que termine la tarea en curso.", True)
            return
        self.job = job
        self.result.hide()
        self.job_label.setText(job.title + "…")
        self.job_bar.setValue(0)
        self.job_box.show()
        self._set_busy(True)
        job.progress.connect(lambda v: self.job_bar.setValue(int(v * 1000)))

        def finished(ok: bool, message: str):
            self.job = None
            self.job_box.hide()
            self._set_busy(False)
            if ok and say_result and message:
                self._say(message)
            elif not ok and message:
                self._say(message, error=True)

        job.finished.connect(finished)
        job.start()

    def _set_busy(self, busy: bool):
        for widget in (self.trim_btn, self.silence_btn, self.transcribe_btn, self.export_btn, self.delete_btn):
            widget.setEnabled(not busy)
        if not busy and self.path:
            self.silence_btn.setEnabled(self.info.get("audio", False))
            self.transcribe_btn.setEnabled(self.info.get("audio", False))

    def closeEvent(self, event):
        if self.job is not None:
            self.job.cancel()
        super().closeEvent(event)

