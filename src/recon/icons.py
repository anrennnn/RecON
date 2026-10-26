"""Iconos de línea dibujados con QPainter.

Los iconos simbólicos de cada escritorio no se recolorean bien fuera de GTK y
Breeze, y cargar SVG obliga a depender del módulo de Qt para SVG. Dibujarlos
aquí los deja nítidos en cualquier escala y del color del texto del tema.
Se diseñan en una cuadrícula de 24×24.
"""

import math

from .qt import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPointF, QRectF, Qt


def _path(*points, close=False) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for p in points[1:]:
        path.lineTo(QPointF(*p))
    if close:
        path.closeSubpath()
    return path


def _rounded(x, y, w, h, r) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def _circle(cx, cy, r) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def _arc(cx, cy, r, start, span) -> QPainterPath:
    rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    path = QPainterPath()
    path.arcMoveTo(rect, start)
    path.arcTo(rect, start, span)
    return path


def _slash() -> QPainterPath:
    return _path((3, 3), (21, 21))


# Cada icono: lista de (trazo, relleno). Relleno True = se pinta por dentro.
def _shapes(name: str) -> list[tuple[QPainterPath, bool]]:
    if name == "monitor":
        return [(_rounded(2.5, 3.5, 19, 13, 2), False), (_path((8, 20.5), (16, 20.5)), False),
                (_path((12, 16.5), (12, 20.5)), False)]
    if name == "window":
        return [(_rounded(2.5, 4, 19, 16, 2), False), (_path((2.5, 8.5), (21.5, 8.5)), False),
                (_circle(5.5, 6.25, 0.6), True), (_circle(7.7, 6.25, 0.6), True)]
    if name == "area":
        return [(_path((3, 8), (3, 3), (8, 3)), False), (_path((16, 3), (21, 3), (21, 8)), False),
                (_path((21, 16), (21, 21), (16, 21)), False), (_path((8, 21), (3, 21), (3, 16)), False),
                (_rounded(8, 8, 8, 8, 1), False)]
    if name == "camera":
        return [(_rounded(2.5, 6, 13.5, 12, 2.5), False), (_path((16, 10.5), (21.5, 7.5), (21.5, 16.5), (16, 13.5)), False)]
    if name == "camera-off":
        return [*_shapes("camera"), (_slash(), False)]
    if name == "mic":
        return [(_rounded(9, 2.5, 6, 11.5, 3), False), (_arc(12, 10.5, 6.5, 180, 180), False),
                (_path((12, 17), (12, 21)), False), (_path((8.5, 21), (15.5, 21)), False)]
    if name == "mic-off":
        return [*_shapes("mic"), (_slash(), False)]
    if name == "speaker":
        return [(_path((4, 9.5), (7.5, 9.5), (12, 5), (12, 19), (7.5, 14.5), (4, 14.5), close=True), False),
                (_arc(13, 12, 4, -50, 100), False), (_arc(13, 12, 7.5, -50, 100), False)]
    if name == "speaker-off":
        return [(_path((4, 9.5), (7.5, 9.5), (12, 5), (12, 19), (7.5, 14.5), (4, 14.5), close=True), False),
                (_path((15.5, 9.5), (20.5, 14.5)), False), (_path((20.5, 9.5), (15.5, 14.5)), False)]
    if name == "gear":
        path = QPainterPath()
        teeth = 8
        for i in range(teeth * 2):
            angle = math.pi * i / teeth
            r = 9.3 if i % 2 == 0 else 7.2
            for d in (-0.17, 0.17):
                x, y = 12 + r * math.cos(angle + d), 12 + r * math.sin(angle + d)
                if i == 0 and d < 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
        path.closeSubpath()
        return [(path, False), (_circle(12, 12, 3), False)]
    if name == "library":
        return [(_rounded(3, 3, 7.5, 7.5, 1.5), False), (_rounded(13.5, 3, 7.5, 7.5, 1.5), False),
                (_rounded(3, 13.5, 7.5, 7.5, 1.5), False), (_rounded(13.5, 13.5, 7.5, 7.5, 1.5), False)]
    if name == "close":
        return [(_path((6, 6), (18, 18)), False), (_path((18, 6), (6, 18)), False)]
    if name == "pause":
        return [(_rounded(6.5, 5, 3.5, 14, 1), True), (_rounded(14, 5, 3.5, 14, 1), True)]
    if name == "play":
        return [(_path((8, 5), (19, 12), (8, 19), close=True), True)]
    if name == "stop":
        return [(_rounded(6, 6, 12, 12, 2.5), True)]
    if name == "record":
        return [(_circle(12, 12, 6.5), True)]
    if name == "trash":
        return [(_path((4, 6.5), (20, 6.5)), False), (_path((9.5, 6.5), (9.5, 4), (14.5, 4), (14.5, 6.5)), False),
                (_path((6, 6.5), (7, 20), (17, 20), (18, 6.5)), False), (_path((10, 10.5), (10, 16)), False),
                (_path((14, 10.5), (14, 16)), False)]
    if name == "copy":
        return [(_rounded(8.5, 8.5, 12, 12, 2), False), (_path((15.5, 8.5), (15.5, 5.5), (13.5, 3.5), (5.5, 3.5),
                                                               (3.5, 5.5), (3.5, 13.5), (5.5, 15.5), (8.5, 15.5)), False)]
    if name == "folder":
        return [(_path((3, 6.5), (3, 18), (4.5, 19.5), (19.5, 19.5), (21, 18), (21, 9.5), (19.5, 8), (11.5, 8),
                       (9.5, 5), (4.5, 5), close=True), False)]
    if name == "scissors":
        return [(_circle(6.5, 6.5, 2.8), False), (_circle(6.5, 17.5, 2.8), False),
                (_path((8.8, 8.3), (20, 18)), False), (_path((8.8, 15.7), (20, 6)), False)]
    if name == "silence":
        bars = [(3, 10, 14), (6.5, 7, 17), (10, 11.5, 12.5), (14, 11.5, 12.5), (17.5, 6, 18), (21, 9, 15)]
        return [(_path((x, y1), (x, y2)), False) for x, y1, y2 in bars]
    if name == "text":
        return [(_path((4, 6), (20, 6)), False), (_path((4, 10.5), (20, 10.5)), False),
                (_path((4, 15), (16, 15)), False), (_path((4, 19.5), (11, 19.5)), False)]
    if name == "export":
        return [(_path((12, 15), (12, 3.5)), False), (_path((7.5, 8), (12, 3.5), (16.5, 8)), False),
                (_path((5, 12), (5, 19), (6.5, 20.5), (17.5, 20.5), (19, 19), (19, 12)), False)]
    if name == "check":
        return [(_path((5, 12.5), (10, 17.5), (19.5, 7)), False)]
    if name == "chevron":
        return [(_path((7, 10), (12, 15), (17, 10)), False)]
    if name == "replay":
        return [(_arc(12, 12, 8, 120, 300), False), (_path((4.5, 4.5), (4.5, 9), (9, 9)), False),
                (_path((12, 8), (12, 12), (15, 14)), False)]
    if name == "search":
        return [(_circle(10.5, 10.5, 6.5), False), (_path((15.5, 15.5), (20.5, 20.5)), False)]
    if name == "plus":
        return [(_path((12, 5), (12, 19)), False), (_path((5, 12), (19, 12)), False)]
    if name == "more":
        return [(_circle(5.5, 12, 1.4), True), (_circle(12, 12, 1.4), True), (_circle(18.5, 12, 1.4), True)]
    raise KeyError(name)


def paint(painter: QPainter, name: str, rect: QRectF, color: QColor, width: float = 1.7):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(rect.x(), rect.y())
    scale = min(rect.width(), rect.height()) / 24
    painter.scale(scale, scale)
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    for path, filled in _shapes(name):
        if filled:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
        else:
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    painter.restore()


def icon(name: str, color: QColor, size: int = 20, ratio: float = 2.0) -> QIcon:
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint(painter, name, QRectF(0, 0, size, size), color)
    painter.end()
    return QIcon(pixmap)
