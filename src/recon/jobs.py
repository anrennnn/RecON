"""Tareas en segundo plano (FFmpeg y la transcripción) con su progreso.

Cada tarea es una lista de pasos; cada paso, un programa que se lanza con
QProcess, así la interfaz no se congela. FFmpeg informa del avance con
«-progress pipe:1» (out_time_us) y se convierte en un porcentaje.
"""

import json
from pathlib import Path

from .qt import QObject, QProcess, pyqtSignal


class Step:
    def __init__(self, program: str, args: list[str], duration: float = 0.0, weight: float = 1.0,
                 on_output=None, before=None):
        self.program = program
        self.args = args
        self.duration = duration  # segundos de vídeo que procesa (para el porcentaje)
        self.weight = weight
        self.on_output = on_output  # recibe cada línea de stdout y stderr
        self.before = before  # función que se llama justo antes (puede rehacer args)


class Job(QObject):
    progress = pyqtSignal(float)          # 0..1
    finished = pyqtSignal(bool, str)      # correcto, mensaje de error

    def __init__(self, title: str, steps: list[Step], parent=None, on_success=None):
        super().__init__(parent)
        self.title = title
        self.steps = steps
        self.on_success = on_success
        self.index = -1
        self.process = None
        self.stderr_tail: list[str] = []
        self.cancelled = False
        self.total_weight = sum(s.weight for s in steps) or 1.0
        self.done_weight = 0.0

    def start(self):
        self._next()

    def cancel(self):
        self.cancelled = True
        if self.process is not None:
            self.process.kill()

    def _next(self):
        if self.index >= 0:
            self.done_weight += self.steps[self.index].weight
        self.index += 1
        if self.index >= len(self.steps):
            self.progress.emit(1.0)
            message = ""
            if self.on_success is not None:
                try:
                    message = self.on_success() or ""
                except Exception as exc:  # noqa: BLE001
                    self.finished.emit(False, str(exc))
                    return
            self.finished.emit(True, message)
            return
        step = self.steps[self.index]
        if step.before is not None:
            try:
                skip = step.before(step)
            except Exception as exc:  # noqa: BLE001
                self.finished.emit(False, str(exc))
                return
            if skip:
                self._next()
                return
        self.process = QProcess(self)
        self.process.setProgram(step.program)
        self.process.setArguments(step.args)
        self.process.readyReadStandardOutput.connect(self._stdout)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._done)
        self.process.errorOccurred.connect(self._error)
        self.stderr_tail = []
        self.process.start()

    def _emit_step_fraction(self, fraction: float):
        step = self.steps[self.index]
        value = (self.done_weight + step.weight * max(0.0, min(1.0, fraction))) / self.total_weight
        self.progress.emit(value)

    def _stdout(self):
        step = self.steps[self.index]
        data = bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        for line in data.splitlines():
            if line.startswith("out_time_us=") and step.duration > 0:
                try:
                    self._emit_step_fraction(int(line.split("=", 1)[1]) / 1e6 / step.duration)
                except ValueError:
                    pass
            elif line.startswith("PROGRESO "):  # de la transcripción
                try:
                    self._emit_step_fraction(float(line.split()[1]))
                except (IndexError, ValueError):
                    pass
            if step.on_output:
                step.on_output(line)

    def _stderr(self):
        step = self.steps[self.index]
        data = bytes(self.process.readAllStandardError()).decode(errors="replace")
        for line in data.splitlines():
            self.stderr_tail = [*self.stderr_tail[-30:], line]
            if step.on_output:
                step.on_output(line)

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.finished.emit(False, f"No se encontró «{self.steps[self.index].program}».")

    def _done(self, code, _status):
        if self.cancelled:
            self.finished.emit(False, "")
            return
        if code != 0:
            detail = next((ln for ln in reversed(self.stderr_tail) if ln.strip()), "")
            self.finished.emit(False, detail or f"El proceso terminó con el código {code}.")
            return
        self._next()


def ffmpeg_args(*args) -> list[str]:
    return ["-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats", *args]


def probe(path: Path) -> dict:
    """Duración, tamaño y si tiene sonido (ffprobe, síncrono: tarda milisegundos)."""
    import subprocess

    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,width,height",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=10,
        ).stdout
        data = json.loads(out or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        data = {}
    info = {"duration": 0.0, "width": 0, "height": 0, "audio": False, "size": 0}
    fmt = data.get("format", {})
    try:
        info["duration"] = float(fmt.get("duration", 0) or 0)
        info["size"] = int(fmt.get("size", 0) or 0)
    except ValueError:
        pass
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and not info["width"]:
            info["width"], info["height"] = stream.get("width", 0), stream.get("height", 0)
        elif stream.get("codec_type") == "audio":
            info["audio"] = True
    return info
