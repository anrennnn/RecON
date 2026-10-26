"""Operaciones con los archivos de vídeo: copiar al portapapeles, papelera, renombrar, mostrar."""

import shutil
import subprocess
from pathlib import Path

from .qt import QApplication, QByteArray, QDesktopServices, QMimeData, QUrl, QtCore

# Archivos que acompañan a cada vídeo (misma base de nombre).
SIDECARS = (".srt", ".txt")


def siblings(video: Path) -> list[Path]:
    return [p for p in (video.with_suffix(s) for s in SIDECARS) if p.exists()]


def mime_for(paths: list[Path]) -> QMimeData:
    """Archivos como los copia un gestor de archivos: se pegan en chats, correos y carpetas."""
    data = QMimeData()
    urls = [QUrl.fromLocalFile(str(p)) for p in paths]
    data.setUrls(urls)
    uri_list = "\r\n".join(u.toString() for u in urls) + "\r\n"
    data.setData("text/uri-list", QByteArray(uri_list.encode()))
    gnome = "copy\n" + "\n".join(u.toString() for u in urls)
    data.setData("x-special/gnome-copied-files", QByteArray(gnome.encode()))
    data.setData("application/x-kde-cutselection", QByteArray(b"0"))
    return data


def copy_to_clipboard(paths: list[Path]):
    QApplication.clipboard().setMimeData(mime_for(paths))


def copy_text(text: str):
    QApplication.clipboard().setText(text)


def show_in_folder(path: Path):
    """Abre la carpeta con el archivo seleccionado (si el gestor de archivos lo permite)."""
    if shutil.which("gdbus"):
        try:
            subprocess.run(
                ["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
                 "--object-path", "/org/freedesktop/FileManager1",
                 "--method", "org.freedesktop.FileManager1.ShowItems",
                 f"['{QUrl.fromLocalFile(str(path)).toString()}']", ""],
                capture_output=True, timeout=3, check=True,
            )
            return
        except (OSError, subprocess.SubprocessError):
            pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def open_file(path: Path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _to_trash(path: Path) -> bool:
    """QFile.moveToTrash devuelve (correcto, ruta en la papelera) en PyQt."""
    result = QtCore.QFile.moveToTrash(str(path))
    return bool(result[0] if isinstance(result, tuple) else result)


def trash(path: Path) -> bool:
    """A la papelera (se puede recuperar), con sus subtítulos."""
    ok = True
    for item in [path, *siblings(path)]:
        if not _to_trash(item):
            try:
                if shutil.which("gio"):
                    subprocess.run(["gio", "trash", str(item)], check=True, capture_output=True, timeout=5)
                else:
                    ok = False
            except (OSError, subprocess.SubprocessError):
                ok = False
    return ok


def rename(video: Path, title: str) -> Path:
    """Cambia el nombre del vídeo y de sus subtítulos. Devuelve la ruta nueva."""
    from .processing import unique
    from .recorder import safe_name

    title = safe_name(title)
    if title == video.stem:
        return video
    target = unique(video.with_name(title + video.suffix))
    for side in siblings(video):
        side.rename(target.with_suffix(side.suffix))
    video.rename(target)
    return target


def replace(original: Path, new: Path) -> Path:
    """Pone new en el sitio de original; el original va a la papelera por si acaso."""
    # Los subtítulos ya no coinciden con el vídeo cortado: van a la papelera con él.
    for side in siblings(original):
        _to_trash(side) or side.unlink(missing_ok=True)
    _to_trash(original) or original.unlink(missing_ok=True)
    new.rename(original)
    return original
