"""Repetición instantánea (como «Grabar lo que ha pasado» de la Xbox Game Bar).

Mientras está activa, la pantalla se graba sin parar en trozos de 5 segundos
dentro de ~/.cache/recon/repeticion y solo se guardan los últimos. Con el atajo
(Super+Alt+G) se cierra el trozo actual y se unen los últimos N segundos en un
vídeo nuevo de la biblioteca. Mientras hay una grabación normal, se detiene.
"""

import math
import shutil
from datetime import datetime
from pathlib import Path

from . import config, devices, gst, pipeline, processing, screens
from .gst import Gst, quote
from .jobs import Job, Step, ffmpeg_args, probe
from .qt import QObject, QTimer, pyqtSignal
from .screencast import ScreenCast

FRAGMENT_SECONDS = 5


class ReplayBuffer(QObject):
    saved = pyqtSignal(object)    # Path
    failed = pyqtSignal(str)
    running_changed = pyqtSignal(bool)

    def __init__(self, settings: config.Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.portal = ScreenCast()
        self.pipe = None
        self.fragments: list[Path] = []
        self.waiting_save = False
        self.suspended = False
        self.job = None
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self._collect)

    @property
    def running(self) -> bool:
        return self.pipe is not None

    # --- encender y apagar ---------------------------------------------------------

    def sync(self):
        """Arranca o para según los ajustes (y si hay una grabación normal en curso)."""
        if self.settings["repeticion"] and not self.suspended:
            self.start()
        else:
            self.stop()

    def suspend(self, value: bool):
        self.suspended = value
        self.sync()

    def start(self):
        if self.running or gst.Gst is None:
            return
        if config.session_type() == "wayland":
            token = self.settings["permisos_pantalla"].get("repeticion", "")
            self.portal.start("pantalla", token, self._portal_done)
        else:
            rect = screens.native_rect(screens.QGuiApplication.primaryScreen())
            source = (f"ximagesrc use-damage=false show-pointer=true startx={rect.x()} starty={rect.y()} "
                      f"endx={rect.right()} endy={rect.bottom()}")
            self._launch(source, (rect.width(), rect.height()))

    def _portal_done(self, ok: bool, message: str, token: str):
        if not ok:
            self.settings.set("repeticion", False)
            if message:
                self.failed.emit(message)
            return
        if token:
            tokens = dict(self.settings["permisos_pantalla"])
            tokens["repeticion"] = token
            self.settings.set("permisos_pantalla", tokens)
        stream = self.portal.streams[0]
        from .recorder import pipewire_source

        size = stream.size if stream.size[0] > 0 else (1920, 1080)
        ratio = screens.QGuiApplication.primaryScreen().devicePixelRatio()
        self._launch(pipewire_source(self.portal.open_remote(), stream.node),
                     (round(size[0] * ratio), round(size[1] * ratio)))

    def _launch(self, source: str, size: tuple[int, int]):
        shutil.rmtree(config.REPLAY_DIR, ignore_errors=True)
        config.REPLAY_DIR.mkdir(parents=True, exist_ok=True)
        fps = int(self.settings["fps"])
        w, h = pipeline.fit(*size, 1080)
        location = config.REPLAY_DIR / "trozo-%05d.mkv"
        parts = [
            f"splitmuxsink name=split location={quote(str(location))} muxer-factory=matroskamux "
            f"max-size-time={FRAGMENT_SECONDS * Gst.SECOND} send-keyframe-requests=true",
            f"{source} ! queue max-size-buffers=4 leaky=downstream ! videoconvert ! videorate "
            f"! video/x-raw,framerate={fps}/1 ! videoscale ! video/x-raw,width={w},height={h},pixel-aspect-ratio=1/1 "
            f"! videoconvert ! video/x-raw,format=I420 ! queue max-size-buffers=0 max-size-bytes=0 "
            f"max-size-time=3000000000 ! {gst.h264_encoder(fps)} ! h264parse ! split.video",
        ]
        audio = []
        if self.settings["microfono"]:
            audio.append(devices.audio_source(self.settings["microfono"]))
        if self.settings["audio_sistema"]:
            audio.append(devices.audio_source(devices.SYSTEM_AUDIO))
        raw = "audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2"
        if len(audio) == 1:
            parts.append(f"{audio[0]} ! queue ! {raw} ! audioconvert ! opusenc bitrate=128000 ! queue ! split.audio_0")
        elif audio:
            parts.append("audiomixer name=amix ! audioconvert ! opusenc bitrate=128000 ! queue ! split.audio_0")
            parts += [f"{a} ! queue ! {raw} ! queue ! amix." for a in audio]
        try:
            pipe = Gst.parse_launch("  ".join(parts))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"No se pudo activar la repetición instantánea: {exc}")
            return
        bus = pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)
        self.fragments = []
        self.pipe = pipe
        if pipe.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.stop()
            self.failed.emit("No se pudo activar la repetición instantánea.")
            return
        self.running_changed.emit(True)

    def stop(self):
        if self.pipe is not None:
            self.pipe.get_bus().remove_signal_watch()
            self.pipe.set_state(Gst.State.NULL)
            self.pipe = None
            self.running_changed.emit(False)
        self.portal.close()
        self.fragments = []

    def _on_message(self, _bus, message):
        if message.type == Gst.MessageType.ELEMENT:
            s = message.get_structure()
            if s is not None and s.get_name() == "splitmuxsink-fragment-closed":
                self._fragment_closed(Path(s.get_string("location")))
        elif message.type == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            self.stop()
            self.failed.emit(f"La repetición instantánea se detuvo: {error.message}")

    def _fragment_closed(self, path: Path):
        self.fragments.append(path)
        keep = math.ceil(self.settings["repeticion_segundos"] / FRAGMENT_SECONDS) + 2
        while len(self.fragments) > keep:
            self.fragments.pop(0).unlink(missing_ok=True)
        if self.waiting_save:
            self.save_timer.start(150)

    # --- guardar ------------------------------------------------------------------

    def save(self):
        if not self.running:
            self.failed.emit("La repetición instantánea está desactivada. Actívala en Ajustes.")
            return
        if self.waiting_save or self.job is not None:
            return
        split = self.pipe.get_by_name("split")
        self.waiting_save = True
        split.emit("split-now")
        self.save_timer.start(4000)  # por si el trozo tarda en cerrarse

    def _collect(self):
        self.waiting_save = False
        fragments = [f for f in self.fragments if f.exists() and f.stat().st_size > 4096]
        if not fragments:
            self.failed.emit("Todavía no hay nada que guardar: espera unos segundos.")
            return
        wanted = float(self.settings["repeticion_segundos"])
        # Copia los trozos: el búfer sigue grabando y borrando los viejos.
        work = config.CACHE_DIR / "repeticion-guardando"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        copies = []
        for fragment in fragments:
            target = work / fragment.name
            shutil.copy2(fragment, target)
            copies.append(target)
        total = sum(probe(c)["duration"] for c in copies)
        start = max(total - wanted, 0.0)
        listing = work / "lista.txt"
        listing.write_text("".join(f"file '{c}'\n" for c in copies), encoding="utf-8")
        name = datetime.now().strftime("Repetición %Y-%m-%d %H.%M.%S") + ".mp4"
        out = processing.unique(self.settings.output_dir() / name)
        args = ["-ss", f"{start:.2f}", "-f", "concat", "-safe", "0", "-i", str(listing), "-map", "0",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)]
        self.job = Job("Guardando la repetición", [Step("ffmpeg", ffmpeg_args(*args), wanted)], self,
                       lambda: shutil.rmtree(work, ignore_errors=True))

        def finished(ok: bool, message: str):
            self.job = None
            if ok:
                self.saved.emit(out)
            else:
                self.failed.emit(f"No se pudo guardar la repetición: {message}")

        self.job.finished.connect(finished)
        self.job.start()
