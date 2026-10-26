"""Ventanas que se ven alrededor de la grabación: elegir área, cuenta atrás y la barra de control."""

from . import icons, screens, theme
from .processing import format_duration
from .qt import (
    QColor, QFont, QHBoxLayout, QLabel, QPainter, QPainterPath, QPen, QPoint, QPushButton,
    QRect, QRectF, Qt, QTimer, QWidget, event_pos, pyqtSignal,
)
from .widgets import IconButton


def _overlay_flags(widget: QWidget, tool: bool = True):
    flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
    if tool:
        flags |= Qt.WindowType.Tool
    widget.setWindowFlags(flags)
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def _shape(widget: QWidget, path: QPainterPath):
    """Sin compositor (X11), la forma se recorta con una máscara para que no salga un recuadro negro."""
    if not screens.composited():
        from .qt import QRegion

        widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


# --- Elegir un área -----------------------------------------------------------------------


class AreaPicker(QWidget):
    """Oscurece la pantalla; se arrastra para marcar el área. Intro confirma, Esc cancela."""

    picked = pyqtSignal(str, QRect)   # nombre de la pantalla, rectángulo relativo a ella (lógico)
    cancelled = pyqtSignal()

    def __init__(self, previous: QRect | None = None):
        super().__init__()
        _overlay_flags(self, tool=False)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.screen_obj = screens.screen_at_cursor()
        self.setGeometry(self.screen_obj.geometry())
        # Sin compositor no hay transparencia: se pinta una captura de la pantalla debajo.
        self.background = None if screens.composited() else self.screen_obj.grabWindow(0)
        self.origin: QPoint | None = None
        self.rect_sel = QRect(previous) if previous is not None and not previous.isEmpty() else QRect()
        if not self.rect_sel.isEmpty() and not QRect(QPoint(0, 0), self.size()).contains(self.rect_sel):
            self.rect_sel = QRect()
        self.confirm = QPushButton("Grabar esta área", self)
        self.confirm.setObjectName("primary")
        self.confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm.clicked.connect(self._accept)
        self.confirm.adjustSize()
        self._place_button()

    def start(self):
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def _place_button(self):
        if self.rect_sel.width() < 40 or self.rect_sel.height() < 40:
            self.confirm.hide()
            return
        b = self.confirm.sizeHint()
        x = self.rect_sel.right() - b.width()
        y = self.rect_sel.bottom() + 10
        if y + b.height() > self.height() - 10:
            y = self.rect_sel.bottom() - b.height() - 10
        self.confirm.setGeometry(max(x, 10), y, b.width(), b.height())
        self.confirm.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event_pos(event)
            self.rect_sel = QRect(self.origin, self.origin)
            self.confirm.hide()
            self.update()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.rect_sel = QRect(self.origin, event_pos(event)).normalized()
            self.update()

    def mouseReleaseEvent(self, _event):
        self.origin = None
        self._place_button()
        self.update()

    def mouseDoubleClickEvent(self, _event):
        self._accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._accept()

    def _accept(self):
        if self.rect_sel.width() < 40 or self.rect_sel.height() < 40:
            return
        self.close()
        self.picked.emit(self.screen_obj.name(), QRect(self.rect_sel))

    def paintEvent(self, _event):
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.background is not None:
            painter.drawPixmap(self.rect(), self.background)
        veil = QPainterPath()
        veil.addRect(QRectF(self.rect()))
        if not self.rect_sel.isEmpty():
            hole = QPainterPath()
            hole.addRect(QRectF(self.rect_sel))
            veil = veil.subtracted(hole)
        painter.fillPath(veil, QColor(0, 0, 0, 120))
        if not self.rect_sel.isEmpty():
            painter.setPen(QPen(t.accent, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(self.rect_sel).adjusted(-1, -1, 1, 1))
            ratio = self.screen_obj.devicePixelRatio()
            size = f"{round(self.rect_sel.width() * ratio)} × {round(self.rect_sel.height() * ratio)}"
            self._pill(painter, size, QPoint(self.rect_sel.x(), max(self.rect_sel.y() - 34, 8)), left=True)
        hint = "Arrastra para elegir el área  ·  Intro para grabar  ·  Esc para cancelar"
        self._pill(painter, hint, QPoint(self.width() // 2, 28))
        painter.end()

    def _pill(self, painter: QPainter, text: str, anchor: QPoint, left: bool = False):
        fm = painter.fontMetrics()
        w, h = fm.horizontalAdvance(text) + 24, fm.height() + 12
        x = anchor.x() if left else anchor.x() - w // 2
        rect = QRectF(x, anchor.y(), w, h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 20, 210))
        painter.drawRoundedRect(rect, h / 2, h / 2)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)


# --- Cuenta atrás ---------------------------------------------------------------------------


class Countdown(QWidget):
    """3, 2, 1… en el centro de la pantalla. La grabación empieza cuando se cierra,
    así la cuenta atrás no sale en el vídeo."""

    finished = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, seconds: int, hint: str):
        super().__init__()
        _overlay_flags(self)
        self.remaining = seconds
        self.hint = hint
        self.resize(260, 300)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self):
        screen = screens.screen_at_cursor().geometry()
        self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)
        shape = QPainterPath()
        shape.addEllipse(QRectF(40, 20, 180, 180))
        shape.addRoundedRect(QRectF(0, 222, self.width(), 30), 15, 15)
        _shape(self, shape)
        self.show()
        self.raise_()
        self.activateWindow()
        self.timer.start(1000)

    def _tick(self):
        self.remaining -= 1
        if self.remaining <= 0:
            self.timer.stop()
            self.hide()
            # Un instante para que el escritorio quite la ventana antes del primer fotograma.
            QTimer.singleShot(180, self._done)
            return
        self.update()

    def _done(self):
        self.close()
        self.finished.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.timer.stop()
            self.close()
            self.cancelled.emit()

    def mousePressEvent(self, _event):
        # Un clic se salta la espera.
        self.timer.stop()
        self.remaining = 0
        self._tick()

    def paintEvent(self, _event):
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = QRectF(40, 20, 180, 180)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(18, 18, 18, 215))
        painter.drawEllipse(circle)
        painter.setPen(QPen(t.red, 5))
        painter.drawEllipse(circle.adjusted(6, 6, -6, -6))
        font = QFont(self.font())
        font.setPixelSize(86)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(circle, int(Qt.AlignmentFlag.AlignCenter), str(max(self.remaining, 1)))
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        w = fm.horizontalAdvance(self.hint) + 24
        pill = QRectF((self.width() - w) / 2, 222, w, 30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(18, 18, 18, 215))
        painter.drawRoundedRect(pill, 15, 15)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), self.hint)
        painter.end()


# --- Barra de control (como la de la Xbox Game Bar) ----------------------------------------


class _Dot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.paused = False
        self.visible_dot = True
        self.blink = QTimer(self)
        self.blink.timeout.connect(self._blink)
        self.blink.start(700)

    def _blink(self):
        self.visible_dot = not self.visible_dot if not self.paused else True
        self.update()

    def paintEvent(self, _event):
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.paused:
            icons.paint(painter, "pause", QRectF(0, 0, 14, 14), t.sub)
        elif self.visible_dot:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(t.red)
            painter.drawEllipse(QRectF(2, 2, 10, 10))
        painter.end()


class ControlBar(QWidget):
    """Píldora flotante: tiempo, pausa, detener, micrófono y descartar. Se puede arrastrar."""

    stop_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    mic_clicked = pyqtSignal()
    discard_clicked = pyqtSignal()

    def __init__(self, recorder, shortcut_hint: str):
        super().__init__()
        _overlay_flags(self)
        self.recorder = recorder
        self.drag_from: QPoint | None = None
        t = theme.current()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 10, 8)
        layout.setSpacing(4)
        self.dot = _Dot(self)
        self.time = QLabel("0:00", self)
        font = self.time.font()
        font.setWeight(QFont.Weight.DemiBold)
        font.setPointSizeF(font.pointSizeF() + 1)
        self.time.setFont(font)
        self.time.setMinimumWidth(48)
        self.pause_btn = IconButton("pause", "Pausar (" + shortcut_hint.get("pausa", "") + ")", 34, 16, self)
        self.stop_btn = IconButton("stop", "Detener y guardar (" + shortcut_hint.get("grabar", "") + ")", 34, 16, self)
        self.stop_btn.color = t.red
        self.mic_btn = IconButton("mic", "Silenciar el micrófono (" + shortcut_hint.get("micro", "") + ")", 34, 18, self)
        self.discard_btn = IconButton("trash", "Descartar la grabación", 34, 18, self)
        layout.addWidget(self.dot)
        layout.addSpacing(6)
        layout.addWidget(self.time)
        separator = QWidget(self)
        separator.setFixedSize(1, 20)
        separator.setStyleSheet(f"background: {t.border.name()};")
        layout.addWidget(separator)
        for button in (self.pause_btn, self.stop_btn, self.mic_btn, self.discard_btn):
            layout.addWidget(button)

        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        self.mic_btn.clicked.connect(self.mic_clicked.emit)
        self.discard_btn.clicked.connect(self._discard)
        self.confirming = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        recorder.state_changed.connect(lambda _s: self.refresh())
        recorder.mic_changed.connect(self._mic)

    def place(self, avoid: QRect | None = None):
        """Abajo en el centro de la pantalla del puntero (o debajo del área que se graba)."""
        self.adjustSize()
        screen = screens.screen_at_cursor().availableGeometry()
        x = screen.center().x() - self.width() // 2
        y = screen.bottom() - self.height() - 28
        if avoid is not None and avoid.intersects(QRect(x, y, self.width(), self.height())):
            below = avoid.bottom() + 14
            y = below if below + self.height() < screen.bottom() else max(avoid.top() - self.height() - 14, screen.top())
        self.move(x, y)

    def start(self, avoid: QRect | None = None):
        request = self.recorder.request
        self.mic_btn.setVisible(bool(request and (request.mic_key or request.system_audio)))
        self._mic(self.recorder.mic_muted)
        self.place(avoid)
        t = theme.current()
        shape = QPainterPath()
        radius = self.height() / 2 if t.shape.pill_primary else t.shape.radius
        shape.addRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
        _shape(self, shape)
        self.refresh()
        self.show()
        self.timer.start(250)

    def finish(self):
        self.timer.stop()
        self.hide()

    def refresh(self):
        state = self.recorder.state
        self.time.setText(format_duration(self.recorder.elapsed()))
        paused = state in ("paused", "pausing")
        self.dot.paused = paused
        self.pause_btn.set_icon("record" if paused else "pause", theme.current().red if paused else None)
        self.pause_btn.setToolTip("Seguir grabando" if paused else "Pausar")
        if state == "finishing":
            self.time.setText("Guardando…")

    def _mic(self, muted: bool):
        self.mic_btn.set_icon("mic-off" if muted else "mic", theme.current().red if muted else None)

    def _discard(self):
        if not self.confirming:
            self.confirming = True
            self.discard_btn.set_icon("check", theme.current().red)
            self.discard_btn.setToolTip("Pulsa otra vez para descartar")
            QTimer.singleShot(2500, self._reset_discard)
            return
        self._reset_discard()
        self.discard_clicked.emit()

    def _reset_discard(self):
        self.confirming = False
        self.discard_btn.set_icon("trash")
        self.discard_btn.setToolTip("Descartar la grabación")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None and hasattr(handle, "startSystemMove") and handle.startSystemMove():
                return
            self.drag_from = event_pos(event)

    def mouseMoveEvent(self, event):
        if self.drag_from is not None:
            from .qt import global_pos

            self.move(global_pos(event) - self.drag_from)

    def mouseReleaseEvent(self, _event):
        self.drag_from = None

    def paintEvent(self, _event):
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = rect.height() / 2 if t.shape.pill_primary else t.shape.radius
        painter.setPen(QPen(t.border, 1))
        painter.setBrush(t.bg)
        painter.drawRoundedRect(rect, radius, radius)
        painter.end()


def screen_rect_for(screen_name: str, area: QRect | None) -> QRect | None:
    """Rectángulo global del área elegida (para que la barra no la tape)."""
    if area is None:
        return None
    screen = screens.screen_by_name(screen_name)
    if screen is None:
        return None
    return area.translated(screen.geometry().topLeft())

