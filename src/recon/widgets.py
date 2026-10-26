"""Controles pequeños que comparten las ventanas de RecON, pintados con el tema."""

from . import icons, theme
from .qt import (
    QColor, QComboBox, QFont, QHBoxLayout, QImage, QLabel, QPainter, QPainterPath, QPen, QPixmap, QPointF, QRectF,
    QSize, Qt, QTimer, QToolButton, QWidget, QtWidgets, pyqtSignal,
)


class IconButton(QToolButton):
    """Botón con uno de nuestros iconos, del color del texto (o del que se pida)."""

    def __init__(self, name: str, tip: str = "", size: int = 32, icon_size: int = 18, parent=None):
        super().__init__(parent)
        self.icon_name = name
        self.icon_size = icon_size
        self.color = None
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def set_icon(self, name: str, color: QColor | None = None):
        self.icon_name = name
        self.color = color
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        t = theme.current()
        painter = QPainter(self)
        s = self.icon_size
        rect = QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s)
        color = self.color or (t.text if self.isEnabled() else t.faint)
        icons.paint(painter, self.icon_name, rect, color)
        painter.end()


class Segmented(QWidget):
    """Selector de opciones en una sola pieza (como los de GNOME o las pestañas de Breeze)."""

    changed = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str, str]], parent=None, compact: bool = False):
        """options: (clave, texto, icono o "")."""
        super().__init__(parent)
        self.options = options
        self.value = options[0][0]
        self.hovered = -1
        self.compact = compact
        self.enabled_keys = {key for key, _, _ in options}
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        height = theme.current().shape.control_height + (0 if compact else 6)
        self.setFixedHeight(height)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def set_value(self, key: str, emit: bool = False):
        if key not in {k for k, _, _ in self.options}:
            return
        self.value = key
        self.update()
        if emit:
            self.changed.emit(key)

    def set_enabled_keys(self, keys: set[str]):
        self.enabled_keys = keys
        self.update()

    def _rects(self) -> list[QRectF]:
        n = len(self.options)
        pad = 3
        width = (self.width() - pad * 2) / n
        return [QRectF(pad + i * width, pad, width, self.height() - pad * 2) for i in range(n)]

    def sizeHint(self):
        fm = self.fontMetrics()
        widest = max(fm.horizontalAdvance(text) for _, text, _ in self.options)
        return QSize((widest + 52) * len(self.options), self.height())

    def minimumSizeHint(self):
        return QSize(60 * len(self.options), self.height())

    def mouseMoveEvent(self, event):
        from .qt import event_pos

        pos = event_pos(event)
        index = next((i for i, r in enumerate(self._rects()) if r.contains(QPointF(pos))), -1)
        if index != self.hovered:
            self.hovered = index
            self.update()

    def leaveEvent(self, _event):
        self.hovered = -1
        self.update()

    def mousePressEvent(self, event):
        from .qt import event_pos

        pos = event_pos(event)
        for (key, _, _), rect in zip(self.options, self._rects()):
            if rect.contains(QPointF(pos)) and key in self.enabled_keys and key != self.value:
                self.set_value(key, emit=True)

    def keyPressEvent(self, event):
        keys = [k for k, _, _ in self.options if k in self.enabled_keys]
        if self.value not in keys:
            return super().keyPressEvent(event)
        i = keys.index(self.value)
        if event.key() == Qt.Key.Key_Left and i > 0:
            self.set_value(keys[i - 1], emit=True)
        elif event.key() == Qt.Key.Key_Right and i < len(keys) - 1:
            self.set_value(keys[i + 1], emit=True)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _event):
        t = theme.current()
        s = t.shape
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = s.control + 2
        painter.setPen(QPen(t.border, 1) if s.bordered else Qt.PenStyle.NoPen)
        painter.setBrush(t.field if s.bordered else t.button)
        painter.drawRoundedRect(outer, radius, radius)
        for i, ((key, text, icon_name), rect) in enumerate(zip(self.options, self._rects())):
            selected = key == self.value
            enabled = key in self.enabled_keys
            if selected:
                painter.setPen(Qt.PenStyle.NoPen)
                if s.bordered:
                    painter.setBrush(t.selected)
                else:
                    painter.setBrush(t.field if not t.dark else theme.mix(t.text, t.bg, 0.16))
                painter.drawRoundedRect(rect, radius - 2, radius - 2)
            elif i == self.hovered and enabled:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(t.hover)
                painter.drawRoundedRect(rect, radius - 2, radius - 2)
            color = t.text if enabled else t.faint
            if selected and s.bordered:
                color = t.accent if not t.dark else t.text
            font = self.font()
            font.setWeight(QFont.Weight.Medium if selected else QFont.Weight.Normal)
            painter.setFont(font)
            fm = painter.fontMetrics()
            text_w = fm.horizontalAdvance(text) if text else 0
            icon_w = 18 if icon_name else 0
            gap = 7 if icon_name and text else 0
            if icon_name and text and text_w + icon_w + gap > rect.width() - 10:
                text_w, gap = 0, 0  # no cabe: solo el icono
                draw_text = ""
            else:
                draw_text = text
            x = rect.x() + (rect.width() - (text_w + icon_w + gap)) / 2
            if icon_name:
                icons.paint(painter, icon_name, QRectF(x, rect.center().y() - 9, 18, 18), color)
                x += icon_w + gap
            if draw_text:
                painter.setPen(color)
                painter.drawText(QRectF(x, rect.y(), text_w + 2, rect.height()),
                                 int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), draw_text)
        if self.hasFocus():
            painter.setPen(QPen(t.accent, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(outer.adjusted(1, 1, -1, -1), radius, radius)
        painter.end()


class Switch(QtWidgets.QAbstractButton):
    """Interruptor (como el de GNOME y KDE) en lugar de una casilla."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)

    def paintEvent(self, _event):
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = QRectF(1, 2, 40, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(t.accent if on else theme.mix(t.text, t.bg, 0.22))
        painter.drawRoundedRect(track, 10, 10)
        knob_x = track.right() - 18 if on else track.x() + 2
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(knob_x, track.y() + 2, 16, 16))
        if self.hasFocus():
            painter.setPen(QPen(t.accent, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track.adjusted(-1, -1, 1, 1), 11, 11)
        painter.end()

    def sizeHint(self):
        return QSize(42, 24)


class LevelMeter(QWidget):
    """Barra fina con el volumen del micrófono, para ver que te oye antes de grabar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.peak = 0.0
        self.setFixedHeight(4)
        self.decay = QTimer(self)
        self.decay.timeout.connect(self._decay)
        self.decay.start(50)

    def set_db(self, db: float):
        level = max(0.0, min(1.0, (db + 60) / 60))
        self.level = max(level, self.level * 0.7)
        self.update()

    def _decay(self):
        if self.level > 0.001:
            self.level *= 0.85
            self.update()

    def paintEvent(self, _event):
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(t.button)
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 2, 2)
        if self.level > 0:
            color = t.accent if self.level < 0.92 else t.red
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(0, 0, self.width() * self.level, self.height()), 2, 2)
        painter.end()


class CameraPreview(QWidget):
    """Vista previa redonda de la cámara, como quedará la burbuja."""

    def __init__(self, diameter: int = 84, parent=None):
        super().__init__(parent)
        self.image: QImage | None = None
        self.message = ""
        self.setFixedSize(diameter, diameter)

    def set_image(self, image: QImage | None):
        self.image = image
        self.update()

    def paintEvent(self, _event):
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        clip = QPainterPath()
        clip.addEllipse(rect)
        painter.setClipPath(clip)
        painter.fillRect(rect, theme.mix(t.text, t.bg, 0.12))
        if self.image is not None and not self.image.isNull():
            painter.drawImage(rect, self.image)
        else:
            icons.paint(painter, "camera", QRectF(rect.center().x() - 12, rect.center().y() - 12, 24, 24), t.sub)
        painter.setClipping(False)
        painter.setPen(QPen(t.border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)
        painter.end()


class CornerPicker(QWidget):
    """Elige la esquina de la burbuja con un clic en una pantalla en miniatura."""

    changed = pyqtSignal(str)
    CORNERS = ["arriba-izq", "arriba-der", "abajo-izq", "abajo-der"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = "abajo-izq"
        self.setFixedSize(76, 48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Esquina de la burbuja")

    def set_value(self, value: str):
        if value in self.CORNERS:
            self.value = value
            self.update()

    def _dot(self, corner: str) -> QRectF:
        vertical, _, horizontal = corner.partition("-")
        x = 6 if horizontal == "izq" else self.width() - 22
        y = 6 if vertical == "arriba" else self.height() - 22
        return QRectF(x, y, 16, 16)

    def mousePressEvent(self, event):
        from .qt import event_pos

        pos = QPointF(event_pos(event))
        best = min(self.CORNERS, key=lambda c: (self._dot(c).center() - pos).manhattanLength())
        if best != self.value:
            self.value = best
            self.update()
            self.changed.emit(best)

    def paintEvent(self, _event):
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(t.border, 1.2))
        painter.setBrush(t.field)
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 6, 6)
        for corner in self.CORNERS:
            dot = self._dot(corner)
            painter.setPen(Qt.PenStyle.NoPen)
            if corner == self.value:
                painter.setBrush(t.accent)
                painter.drawEllipse(dot)
            else:
                painter.setBrush(t.hover)
                painter.drawEllipse(dot.adjusted(3, 3, -3, -3))
        painter.end()


class Combo(QComboBox):
    """Desplegable con nuestra flecha (la del estilo se oculta en la hoja de estilos)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        t = theme.current()
        icons.paint(painter, "chevron", QRectF(self.width() - 26, (self.height() - 16) / 2, 16, 16), t.sub)
        painter.end()

    def set_data(self, value):
        index = self.findData(value)
        if index >= 0:
            self.setCurrentIndex(index)
        return index >= 0


def row(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        elif isinstance(widget, int):
            layout.addSpacing(widget)
        else:
            layout.addWidget(widget)
    return layout


def label(text: str, name: str = "", parent=None) -> QLabel:
    widget = QLabel(text, parent)
    if name:
        widget.setObjectName(name)
    return widget


def rounded_pixmap(image: QImage, width: int, height: int, radius: float) -> QPixmap:
    """Miniatura recortada a esquinas redondeadas (biblioteca y revisión)."""
    pixmap = QPixmap(width * 2, height * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), radius, radius)
    painter.setClipPath(path)
    if image is not None and not image.isNull():
        scaled = image.scaled(width * 2, height * 2, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
        sx = (scaled.width() / 2 - width) / 2
        sy = (scaled.height() / 2 - height) / 2
        painter.drawImage(QRectF(-sx, -sy, scaled.width() / 2, scaled.height() / 2), scaled)
    else:
        painter.fillRect(QRectF(0, 0, width, height), theme.current().button)
    painter.end()
    return pixmap
