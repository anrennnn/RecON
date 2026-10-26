"""Pantallas y ventanas: dónde está cada una en píxeles reales (X11) y lista de ventanas."""

import os
import re
import shutil
import subprocess

from .qt import QCursor, QGuiApplication, QRect


def native_rect(screen) -> QRect:
    """Rectángulo de la pantalla en píxeles reales (Qt trabaja en píxeles lógicos)."""
    g, ratio = screen.geometry(), screen.devicePixelRatio()
    return QRect(round(g.x() * ratio), round(g.y() * ratio), round(g.width() * ratio), round(g.height() * ratio))


def screen_at_cursor():
    return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()


def screen_by_name(name: str):
    for screen in QGuiApplication.screens():
        if screen.name() == name:
            return screen
    return None


def screen_label(screen) -> str:
    rect = native_rect(screen)
    model = (screen.model() or screen.manufacturer() or "").strip()
    name = f"{model} ({screen.name()})" if model and model != screen.name() else screen.name()
    return f"{name} · {rect.width()}×{rect.height()}"


def _run(*cmd) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        # Con UTF-8, xprop escribe los títulos tal cual y no con escapes octales.
        env = {**os.environ, "LC_ALL": "C.UTF-8"}
        return subprocess.run(cmd, capture_output=True, text=True, timeout=2, env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


_IDS = re.compile(r"0x[0-9a-fA-F]+")


def x11_windows() -> list[tuple[int, str]]:
    """Ventanas normales abiertas (X11), de la de arriba a la de abajo: (id, título)."""
    raw = _run("xprop", "-root", "_NET_CLIENT_LIST_STACKING")
    windows = []
    for xid_text in reversed(_IDS.findall(raw)):
        info = _run("xprop", "-id", xid_text, "_NET_WM_NAME", "WM_NAME", "_NET_WM_WINDOW_TYPE", "_NET_WM_STATE",
                    "_NET_WM_PID")
        if "_NET_WM_WINDOW_TYPE_NORMAL" not in info and "_NET_WM_WINDOW_TYPE" in info and "not found" not in info:
            continue
        if "_NET_WM_STATE_HIDDEN" in info or "_NET_WM_STATE_SKIP_TASKBAR" in info:
            continue
        pid = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", info)
        if pid and int(pid.group(1)) == os.getpid():
            continue
        title = re.search(r'_NET_WM_NAME\(UTF8_STRING\) = "(.*)"', info) or re.search(r'WM_NAME\(\w+\) = "(.*)"', info)
        if title and title.group(1).strip():
            windows.append((int(xid_text, 16), title.group(1)))
    return windows


def x11_active_window() -> int:
    match = _IDS.search(_run("xprop", "-root", "_NET_ACTIVE_WINDOW").split("#")[-1])
    return int(match.group(0), 16) if match else 0


def x11_window_size(xid: int) -> tuple[int, int]:
    info = _run("xwininfo", "-id", str(xid))
    w = re.search(r"Width: (\d+)", info)
    h = re.search(r"Height: (\d+)", info)
    return (int(w.group(1)), int(h.group(1))) if w and h else (1920, 1080)
