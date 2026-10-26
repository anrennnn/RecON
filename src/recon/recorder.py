"""La grabación: preparar la fuente, grabar por trozos, pausar y terminar.

Cada tramo entre pausas es un archivo .mkv aparte dentro de
~/.local/share/recon/en-curso/<grabación>/. Al terminar se unen sin volver a
codificar. Si el equipo se apaga a mitad, los trozos siguen ahí y RecON los
recupera la próxima vez que arranca.
"""

import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config, devices, pipeline, processing, screens
from .gst import Gst
from .qt import QObject, QRect, QTimer, pyqtSignal
from .screencast import ScreenCast

MAX_HEIGHT = {"1080": 1080, "720": 720, "original": 0}


@dataclass
class Request:
    """Lo que el usuario eligió en el panel."""
    mode: str = "pantalla_camara"      # pantalla_camara, pantalla, camara
    source: str = "pantalla"           # pantalla, ventana, area
    screen_name: str = ""
    window: int = 0                    # X11: id de la ventana (0 = la activa)
    area: QRect | None = None          # relativo a la pantalla, en píxeles lógicos
    camera_key: str = ""
    camera: devices.Device | None = None
    mic_key: str = ""
    system_audio: bool = False
    quality: str = "1080"
    fps: int = 30
    bubble_position: str = "abajo-izq"
    bubble_size: str = "m"
    mirror: bool = False
    denoise: bool = True
    title: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def uses_screen(self) -> bool:
        return self.mode in ("pantalla_camara", "pantalla")

    @property
    def uses_camera(self) -> bool:
        return self.mode in ("pantalla_camara", "camara") and bool(self.camera_key)


def default_title() -> str:
    return datetime.now().strftime("Grabación %Y-%m-%d %H.%M.%S")


class Recorder(QObject):
    ready = pyqtSignal()                 # fuente lista: toca la cuenta atrás
    state_changed = pyqtSignal(str)      # idle, preparing, ready, recording, paused, finishing
    mic_changed = pyqtSignal(bool)       # True = silenciado
    finished = pyqtSignal(object)        # Path del MP4
    failed = pyqtSignal(str)
    warning = pyqtSignal(str)            # se sigue grabando, pero sin algo (cámara o sonido)
    saving_progress = pyqtSignal(float)

    def __init__(self, settings: config.Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.portal = ScreenCast()
        self.state = "idle"
        self.request: Request | None = None
        self.spec_base: dict = {}
        self.pipe = None
        self.bus_watch = False
        self.folder: Path | None = None
        self.segments: list[Path] = []
        self.elapsed_before = 0.0
        self.segment_started = 0.0
        self.mic_muted = False
        self.after_segment = None
        self.eos_timer = QTimer(self)
        self.eos_timer.setSingleShot(True)
        self.eos_timer.timeout.connect(self._segment_closed)
        self.job = None

    # --- estado -------------------------------------------------------------------

    def _set_state(self, state: str):
        self.state = state
        self.state_changed.emit(state)

    @property
    def busy(self) -> bool:
        return self.state != "idle"

    def elapsed(self) -> float:
        if self.state == "recording":
            return self.elapsed_before + time.monotonic() - self.segment_started
        return self.elapsed_before

    # --- preparar la fuente ---------------------------------------------------------

    def prepare(self, request: Request):
        if self.busy:
            return
        self.request = request
        self.mic_muted = False
        self._set_state("preparing")
        if not request.uses_screen:
            self._finish_prepare(None, None)
            return
        if config.session_type() == "wayland":
            kind = "ventana" if request.source == "ventana" else "pantalla"
            token = self.settings["permisos_pantalla"].get(kind, "") if kind == "pantalla" else ""
            self.portal.start(kind, token, self._portal_done)
            return
        self._prepare_x11(request)

    def _portal_done(self, ok: bool, message: str, token: str):
        if not ok:
            self._set_state("idle")
            if message:
                self.failed.emit(message)
            return
        if token:
            tokens = dict(self.settings["permisos_pantalla"])
            tokens["pantalla"] = token
            self.settings.set("permisos_pantalla", tokens)
        stream = self.portal.streams[0]
        request = self.request
        width, height = stream.size if stream.size[0] > 0 else (1920, 1080)
        # La pantalla de Qt que coincide con el flujo, para saber su escala.
        screen = screens.screen_by_name(request.screen_name) or screens.screen_at_cursor()
        for candidate in screens.QGuiApplication.screens():
            g = candidate.geometry()
            if (g.x(), g.y()) == tuple(stream.position) and g.width() == width:
                screen = candidate
                break
        ratio = screen.devicePixelRatio() if screen else 1.0
        source_px = (round(width * ratio), round(height * ratio))
        prescale = crop = None
        if request.source == "area" and request.area is not None and stream.source_type != 2:
            a = request.area
            prescale = source_px
            left, top = round(a.x() * ratio), round(a.y() * ratio)
            w, h = round(a.width() * ratio), round(a.height() * ratio)
            crop = (left, top, max(prescale[0] - left - w, 0), max(prescale[1] - top - h, 0))
            source_px = (w, h)
        self._finish_prepare(source_px, {"prescale": prescale, "crop": crop, "node": stream.node})

    def _prepare_x11(self, request: Request):
        display = ""
        if request.source == "ventana":
            xid = request.window or screens.x11_active_window()
            if not xid:
                self._set_state("idle")
                self.failed.emit("No se encontró la ventana que grabar.")
                return
            size = screens.x11_window_size(xid)
            fragment = f"ximagesrc xid={xid} use-damage=false show-pointer=true{display}"
            self._finish_prepare(size, {"fragment": fragment})
            return
        screen = screens.screen_by_name(request.screen_name) or screens.screen_at_cursor()
        rect = screens.native_rect(screen)
        if request.source == "area" and request.area is not None:
            ratio = screen.devicePixelRatio()
            a = request.area
            rect = QRect(rect.x() + round(a.x() * ratio), rect.y() + round(a.y() * ratio),
                         round(a.width() * ratio), round(a.height() * ratio))
        # ximagesrc cuenta el último píxel incluido (QRect.right() = x + ancho - 1).
        fragment = (f"ximagesrc use-damage=false show-pointer=true startx={rect.x()} starty={rect.y()} "
                    f"endx={rect.right()} endy={rect.bottom()}")
        self._finish_prepare((rect.width(), rect.height()), {"fragment": fragment})

    def _finish_prepare(self, source_px, details):
        request = self.request
        max_h = MAX_HEIGHT.get(request.quality, 1080)
        if source_px:
            size = pipeline.fit(*source_px, max_h)
        else:  # solo cámara
            size = (1280, 720) if request.quality == "720" else (1920, 1080)
        self.spec_base = {"size": size, "fps": request.fps, "details": details or {}}
        self._set_state("ready")
        self.ready.emit()

    # --- grabar -------------------------------------------------------------------

    def record(self):
        """Empieza a grabar (tras la cuenta atrás)."""
        if self.state != "ready":
            return
        self.title = self.request.title or default_title()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.folder = config.SEGMENTS_DIR / stamp
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "grabacion.json").write_text(json.dumps(
            {"titulo": self.title, "reducir_ruido": self.request.denoise}, ensure_ascii=False), encoding="utf-8")
        self.segments = []
        self.elapsed_before = 0.0
        if not self._start_segment():
            self._cleanup(remove=True)

    def _build_spec(self, location: Path) -> pipeline.Spec | None:
        request, base = self.request, self.spec_base
        details = base["details"]
        spec = pipeline.Spec(location=str(location), fps=base["fps"], size=base["size"], mirror=request.mirror,
                             mic_muted=self.mic_muted)
        if request.uses_screen:
            if "node" in details:
                try:
                    fd = self.portal.open_remote()
                except Exception as exc:  # noqa: BLE001
                    self.failed.emit(f"No se pudo abrir el flujo de la pantalla: {exc}")
                    return None
                spec.screen = pipewire_source(fd, details["node"])
                spec.prescale = details.get("prescale")
                spec.crop = details.get("crop")
            else:
                spec.screen = details["fragment"]
        if request.uses_camera:
            spec.camera = devices.camera_source(request.camera, request.camera_key)
            if request.uses_screen:
                spec.bubble = pipeline.bubble_geometry(spec.size, request.bubble_position, request.bubble_size)
            else:
                spec.camera_full = True
        if request.mic_key:
            spec.audio.append(devices.audio_source(request.mic_key))
        if request.system_audio:
            spec.audio.append(devices.audio_source(devices.SYSTEM_AUDIO))
        if not request.mic_key and request.system_audio:
            spec.mic_muted = False  # el único sonido es el del sistema: no se silencia con el micro
        return spec

    def _start_segment(self) -> bool:
        location = self.folder / f"trozo-{len(self.segments) + 1:03d}.mkv"
        spec = self._build_spec(location)
        if spec is None:
            return False
        description = pipeline.build(spec)
        try:
            pipe = Gst.parse_launch(description)
        except Exception as exc:  # noqa: BLE001 - GLib.Error con el elemento que falta
            self.failed.emit(f"No se pudo preparar la grabación: {exc}")
            return False
        pipe.use_clock(Gst.SystemClock.obtain())
        bubble = pipe.get_by_name("burbuja")
        if bubble is not None and spec.bubble:
            diameter = spec.bubble[2]
            bubble.connect("draw", lambda *args: pipeline.draw_bubble(*args, diameter))
        bus = pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)
        self.pipe = pipe
        self.segments.append(location)
        if pipe.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            detail, culprit = "", ""
            error = bus.pop_filtered(Gst.MessageType.ERROR)
            if error is not None:
                gerror, debug = error.parse_error()
                detail = f" ({gerror.message})"
                culprit = error.src.get_name() if error.src is not None else ""
                print("Error de GStreamer:", culprit, gerror.message, debug)
            self._teardown()
            self.segments.pop()
            if self._drop_failed_input(culprit):
                return self._start_segment()
            self.failed.emit(f"No se pudo empezar a grabar{detail}.")
            return False
        self.segment_started = time.monotonic()
        self._set_state("recording")
        return True

    def _drop_failed_input(self, element: str) -> bool:
        """Si falla el micrófono o la cámara (p. ej. la usa otra app), se graba sin ella."""
        request = self.request
        if element.startswith(("pulsesrc", "audiotestsrc")) or (
                element.startswith("pipewiresrc") and not request.uses_screen):
            if request.mic_key or request.system_audio:
                request.mic_key, request.system_audio = "", False
                self.warning.emit("No se pudo abrir el micrófono: se graba sin sonido.")
                return True
        if element.startswith(("v4l2src", "decodebin", "jpegdec")) and request.uses_camera and request.uses_screen:
            request.camera_key = ""
            self.warning.emit("La cámara no responde (¿la está usando otra aplicación?): se graba sin ella.")
            return True
        return False

    def _on_message(self, _bus, message):
        if message.type == Gst.MessageType.EOS:
            self._segment_closed()
        elif message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            print("Error de GStreamer:", error.message, debug)
            if self.after_segment is not None:  # ya se estaba cerrando el trozo
                self._segment_closed()
                return
            was_recording = self.state == "recording"
            self._teardown()
            if was_recording:
                self.elapsed_before += time.monotonic() - self.segment_started
            text = error.message
            if "v4l2" in (debug or "") or "video4linux" in text.lower() or "device" in text.lower():
                text = f"La cámara dejó de responder ({error.message})."
            if self._usable_segments():
                self.failed.emit(f"{text} Se guarda lo grabado hasta ahora.")
                self._finalize()
            else:
                self.failed.emit(text)
                self._cleanup(remove=True)

    def _end_segment(self, then):
        """Cierra el archivo del trozo actual (EOS) y luego llama a then()."""
        if self.pipe is None:
            then()
            return
        self.elapsed_before += time.monotonic() - self.segment_started
        self.after_segment = then
        if not pipeline.close_inputs(self.pipe):
            self.pipe.send_event(Gst.Event.new_eos())
        self.eos_timer.start(5000)  # por si alguna fuente no responde

    def _segment_closed(self):
        self.eos_timer.stop()
        self._teardown()
        then, self.after_segment = self.after_segment, None
        if then:
            then()

    def _teardown(self):
        if self.pipe is not None:
            bus = self.pipe.get_bus()
            bus.remove_signal_watch()
            self.pipe.set_state(Gst.State.NULL)
            self.pipe = None

    # --- controles ----------------------------------------------------------------

    def pause(self):
        if self.state == "recording":
            self._set_state("pausing")
            self._end_segment(lambda: self._set_state("paused"))
        elif self.state == "paused":
            self._start_segment()

    def toggle_mic(self):
        self.mic_muted = not self.mic_muted
        if self.pipe is not None:
            volume = self.pipe.get_by_name("micvol")
            if volume is not None:
                volume.set_property("mute", self.mic_muted)
        self.mic_changed.emit(self.mic_muted)

    def stop(self):
        if self.state == "recording":
            self._set_state("finishing")
            self._end_segment(self._finalize)
        elif self.state == "paused":
            self._set_state("finishing")
            self._finalize()
        elif self.state in ("preparing", "ready"):
            self.cancel()

    def cancel(self):
        """Descarta la grabación en curso."""
        if self.state in ("recording", "pausing"):
            self._end_segment(lambda: self._cleanup(remove=True))
        else:
            self._cleanup(remove=True)

    def _usable_segments(self) -> list[Path]:
        return [s for s in self.segments if s.exists() and s.stat().st_size > 4096]

    def _finalize(self):
        self._set_state("finishing")
        segments = self._usable_segments()
        if not segments:
            self.failed.emit("La grabación quedó vacía.")
            self._cleanup(remove=True)
            return
        out = processing.unique(self.settings.output_dir() / f"{safe_name(self.title)}.mp4")
        folder = self.folder

        def done():
            shutil.rmtree(folder, ignore_errors=True)

        self.job = processing.finalize(segments, out, self.request.denoise and bool(self.request.mic_key),
                                       self, done)
        self.job.progress.connect(self.saving_progress.emit)

        def finished(ok, message):
            self.job = None
            self._cleanup(remove=False)
            if ok:
                self.finished.emit(out)
            else:
                self.failed.emit(f"No se pudo guardar el vídeo: {message}. Los trozos siguen en {folder}.")

        self.job.finished.connect(finished)
        self.job.start()

    def _cleanup(self, remove: bool):
        self._teardown()
        if remove and self.folder is not None:
            shutil.rmtree(self.folder, ignore_errors=True)
        self.folder = None
        self.segments = []
        self.elapsed_before = 0.0
        self.portal.close()
        self._set_state("idle")


def pipewire_source(fd: int, node: int) -> str:
    """pipewiresrc con el descriptor del portal. keepalive-time repite el último fotograma
    cuando la pantalla no cambia (PipeWire solo manda fotogramas nuevos si hay cambios)."""
    names = set()
    element = Gst.ElementFactory.make("pipewiresrc", None)
    if element is not None:
        names = {p.name for p in element.list_properties()}
    extra = "".join(f" {k}={v}" for k, v in (("keepalive-time", 1000), ("always-copy", "true")) if k in names)
    return f"pipewiresrc fd={fd} path={node} do-timestamp=true{extra}"


def safe_name(title: str) -> str:
    cleaned = "".join("-" if ch in '/\\\0' else ch for ch in title).strip().strip(".")
    return cleaned[:120] or default_title()


def pending_recordings() -> list[Path]:
    """Grabaciones que se cortaron (apagón, cierre forzado) y tienen trozos sin unir."""
    if not config.SEGMENTS_DIR.exists():
        return []
    return sorted(p for p in config.SEGMENTS_DIR.iterdir() if p.is_dir() and any(p.glob("trozo-*.mkv")))


def recover(folder: Path, settings: config.Settings, parent=None):
    """Job que une los trozos de una grabación cortada. Devuelve (job, ruta) o None."""
    segments = sorted(s for s in folder.glob("trozo-*.mkv") if s.stat().st_size > 4096)
    if not segments:
        shutil.rmtree(folder, ignore_errors=True)
        return None
    try:
        meta = json.loads((folder / "grabacion.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    title = f"{meta.get('titulo') or default_title()} (recuperada)"
    out = processing.unique(settings.output_dir() / f"{safe_name(title)}.mp4")
    job = processing.finalize(segments, out, bool(meta.get("reducir_ruido")), parent,
                              lambda: shutil.rmtree(folder, ignore_errors=True))
    return job, out

