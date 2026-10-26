"""Biblioteca: todas las grabaciones de la carpeta, con miniatura y búsqueda.

La búsqueda mira el nombre y, si el vídeo está transcrito, también lo que se dice
en él: «el vídeo donde expliqué la factura» se encuentra escribiendo «factura».
"""

import hashlib
from datetime import datetime
from pathlib import Path

from . import config, processing, theme, transcribe
from .qt import (
    QFileSystemWatcher, QIcon, QImage, QLineEdit, QListWidget, QListWidgetItem, QObject, QProcess, QSize, Qt,
    QTimer, QVBoxLayout, QWidget, pyqtSignal,
)
from .widgets import IconButton, label, rounded_pixmap, row

VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".gif"}
CARD_W, CARD_H = 224, 126


def _thumb_path(video: Path) -> Path:
    stamp = f"{video}:{video.stat().st_mtime_ns}".encode()
    return config.THUMBS_DIR / (hashlib.sha1(stamp).hexdigest()[:20] + ".jpg")


class ThumbQueue(QObject):
    """Crea las miniaturas de una en una, sin bloquear la ventana."""

    ready = pyqtSignal(str)  # ruta del vídeo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pending: list[Path] = []
        self.process: QProcess | None = None
        self.current: Path | None = None

    def add(self, video: Path):
        if video not in self.pending:
            self.pending.append(video)
        self._next()

    def _next(self):
        if self.process is not None or not self.pending:
            return
        self.current = self.pending.pop(0)
        target = _thumb_path(self.current)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.process = QProcess(self)
        self.process.finished.connect(self._done)
        self.process.start("ffmpeg", ["-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-ss", "1",
                                      "-i", str(self.current), "-frames:v", "1", "-vf", "scale=448:-2",
                                      str(target)])

    def _done(self, *_args):
        video = self.current
        self.process.deleteLater()
        self.process = None
        if video is not None:
            self.ready.emit(str(video))
        self._next()


class LibraryWindow(QWidget):
    open_requested = pyqtSignal(object)   # Path
    record_requested = pyqtSignal()

    def __init__(self, settings: config.Settings):
        super().__init__()
        self.settings = settings
        self.items: dict[str, QListWidgetItem] = {}
        self.texts: dict[str, str] = {}
        self.thumbs = ThumbQueue(self)
        self.thumbs.ready.connect(self._thumb_ready)
        t = theme.current()
        self.setWindowTitle("Biblioteca · RecON")
        self.setObjectName("window")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.resize(780, 600)

        body = QVBoxLayout(self)
        body.setContentsMargins(20, 18, 20, 12)
        body.setSpacing(t.shape.spacing)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Buscar por nombre o por lo que se dice en el vídeo…")
        self.search.setClearButtonEnabled(True)
        self.record_btn = IconButton("record", "Nueva grabación", 36, 18, self)
        self.record_btn.color = t.red
        self.folder_btn = IconButton("folder", "Abrir la carpeta de grabaciones", 36, 18, self)
        body.addLayout(row(label("Grabaciones", "title"), 12, self.search, self.folder_btn, self.record_btn))

        self.list = QListWidget(self)
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setIconSize(QSize(CARD_W, CARD_H))
        self.list.setGridSize(QSize(CARD_W + 18, CARD_H + 62))
        self.list.setSpacing(4)
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.setStyleSheet(
            f"QListWidget::item {{ border-radius: {t.shape.control + 2}px; padding: 6px; color: {t.text.name()}; }}"
            f"QListWidget::item:hover {{ background: {t.hover.name()}; }}"
            f"QListWidget::item:selected {{ background: {t.selected.name()}; color: {t.text.name()}; }}"
        )
        body.addWidget(self.list, 1)
        self.empty = label("Todavía no hay grabaciones. Pulsa el botón rojo o "
                           "usa el atajo para grabar la primera.", "sub", self)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        body.addWidget(self.empty, 1)
        self.status = label("", "hint", self)
        body.addWidget(self.status)

        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _p: self.reload_timer.start(400))
        self.reload_timer = QTimer(self)
        self.reload_timer.setSingleShot(True)
        self.reload_timer.timeout.connect(self.reload)

        self.search.textChanged.connect(self._filter)
        self.list.itemActivated.connect(lambda item: self.open_requested.emit(Path(item.data(Qt.ItemDataRole.UserRole))))
        self.list.itemClicked.connect(lambda item: self.open_requested.emit(Path(item.data(Qt.ItemDataRole.UserRole))))
        self.folder_btn.clicked.connect(self._open_folder)
        self.record_btn.clicked.connect(self.record_requested.emit)

    def open(self):
        self.reload()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    def _open_folder(self):
        from . import files

        files.open_file(self.settings.output_dir())

    def reload(self):
        folder = self.settings.output_dir()
        if str(folder) not in self.watcher.directories():
            for old in self.watcher.directories():
                self.watcher.removePath(old)
            self.watcher.addPath(str(folder))
        videos = sorted((p for p in folder.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES and p.is_file()),
                        key=lambda p: p.stat().st_mtime, reverse=True)
        self.list.clear()
        self.items.clear()
        self.texts.clear()
        placeholder = QIcon(rounded_pixmap(QImage(), CARD_W, CARD_H, theme.current().shape.control))
        total = 0
        for video in videos:
            stat = video.stat()
            total += stat.st_size
            when = datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y")
            item = QListWidgetItem(placeholder, f"{video.stem}\n{when} · {processing.format_size(stat.st_size)}")
            item.setData(Qt.ItemDataRole.UserRole, str(video))
            item.setToolTip(video.name)
            item.setTextAlignment(int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop))
            self.list.addItem(item)
            self.items[str(video)] = item
            self.texts[str(video)] = (video.stem + " " + transcribe.transcript(video)).lower()
            thumb = _thumb_path(video)
            if thumb.exists():
                self._set_thumb(item, thumb)
            elif video.suffix.lower() != ".gif":
                self.thumbs.add(video)
        self.empty.setVisible(not videos)
        self.list.setVisible(bool(videos))
        count = f"{len(videos)} grabación" + ("" if len(videos) == 1 else "es")
        self.status.setText(f"{count} · {processing.format_size(total)} en {folder}" if videos else str(folder))
        self._filter(self.search.text())

    def _set_thumb(self, item: QListWidgetItem, thumb: Path):
        image = QImage(str(thumb))
        if not image.isNull():
            item.setIcon(QIcon(rounded_pixmap(image, CARD_W, CARD_H, theme.current().shape.control)))

    def _thumb_ready(self, video: str):
        item = self.items.get(video)
        if item is not None:
            try:
                self._set_thumb(item, _thumb_path(Path(video)))
            except OSError:
                pass

    def _filter(self, text: str):
        words = text.lower().split()
        shown = 0
        for video, item in self.items.items():
            visible = all(w in self.texts.get(video, "") for w in words)
            item.setHidden(not visible)
            shown += visible
        if words:
            self.status.setText(f"{shown} resultado" + ("" if shown == 1 else "s"))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
