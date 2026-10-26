"""Cámaras y micrófonos, con el monitor de dispositivos de GStreamer.

Cada dispositivo se guarda con una clave de texto («v4l2:/dev/video0»,
«pulse:alsa_input.usb-…») para recordarlo entre sesiones y montar su parte de
la tubería de grabación.
"""

import os
import re
from dataclasses import dataclass

from .gst import Gst, quote

MIC_DEFAULT = "predeterminado"
TEST_CAMERA = "prueba"
SYSTEM_AUDIO = "@DEFAULT_MONITOR@"  # PulseAudio y pipewire-pulse: lo que suena por la salida actual


@dataclass
class Device:
    key: str
    name: str
    caps: object = None  # Gst.Caps de la cámara


def _scan(kind: str) -> list:
    if Gst is None:
        return []
    monitor = Gst.DeviceMonitor.new()
    monitor.add_filter(kind, None)
    try:
        if not monitor.start():
            return []
        return list(monitor.get_devices() or [])
    finally:
        monitor.stop()


def _identify(device) -> tuple[str, str]:
    """(api, identificador) del dispositivo: v4l2, pulse o pipewire."""
    try:
        element = device.create_element(None)
    except Exception:  # noqa: BLE001 - un proveedor roto no debe tumbar la lista
        return "", ""
    if element is None:
        return "", ""
    factory = element.get_factory().get_name()
    if factory == "v4l2src":
        return "v4l2", element.get_property("device") or ""
    if factory == "pulsesrc":
        return "pulse", element.get_property("device") or ""
    if factory == "pipewiresrc":
        props = device.get_properties()
        serial = props.get_value("object.serial") if props and props.has_field("object.serial") else None
        target = str(serial) if serial is not None else (element.get_property("path") or "")
        return "pipewire", target
    return "", ""


def _is_monitor(device) -> bool:
    props = device.get_properties()
    return bool(props and props.has_field("device.class") and props.get_string("device.class") == "monitor")


def _collect(kind: str, preferred: str) -> list[Device]:
    found: dict[str, Device] = {}
    fallback: dict[str, Device] = {}
    for device in _scan(kind):
        if kind == "Audio/Source" and _is_monitor(device):
            continue
        api, ident = _identify(device)
        if not ident:
            continue
        name = device.get_display_name()
        entry = Device(f"{api}:{ident}", name, device.get_caps())
        # Si el mismo aparato sale por PipeWire y por v4l2/pulse, se usa el directo.
        (found if api == preferred else fallback).setdefault(name, entry)
    for name, entry in fallback.items():
        found.setdefault(name, entry)
    return list(found.values())


def cameras() -> list[Device]:
    devices = _collect("Video/Source", "v4l2")
    if os.environ.get("RECON_CAMARA_PRUEBA"):
        devices.insert(0, Device(TEST_CAMERA, "Cámara de prueba"))
    return devices


def microphones() -> list[Device]:
    devices = _collect("Audio/Source", "pulse")
    if os.environ.get("RECON_CAMARA_PRUEBA"):
        devices.insert(0, Device(TEST_CAMERA, "Micrófono de prueba"))
    return devices


# --- Formato de la cámara ----------------------------------------------------------

_FPS_FIELD = re.compile(r"framerate=\(fraction\)(\{[^}]*\}|\[[^\]]*\]|[0-9]+/[0-9]+)")
_FRACTION = re.compile(r"([0-9]+)/([0-9]+)")


def _max_fps(structure_text: str) -> float:
    match = _FPS_FIELD.search(structure_text)
    if not match:
        return 0.0
    rates = [int(n) / int(d) for n, d in _FRACTION.findall(match.group(1)) if int(d)]
    return max(rates, default=0.0)


def camera_format(caps) -> str:
    """El mejor formato para la burbuja: ~720p a 24 fps o más. Las webcams USB suelen dar
    720p fluido solo en MJPEG; en YUYV, 640×480."""
    if caps is None:
        return ""
    best, best_score = "", None
    for i in range(caps.get_size()):
        s = caps.get_structure(i)
        name = s.get_name()
        if name not in ("video/x-raw", "image/jpeg"):
            continue
        ok_w, width = s.get_int("width")
        ok_h, height = s.get_int("height")
        if not (ok_w and ok_h) or height < 240:
            continue
        fps = _max_fps(s.to_string())
        raw = name == "video/x-raw"
        if raw and s.has_field("format") and s.get_string("format") not in ("YUY2", "NV12", "I420", "YV12", None):
            continue
        score = (fps >= 24, -abs(height - 720), raw, fps)
        if best_score is None or score > best_score:
            best_score = score
            fps_text = f",framerate={round(fps)}/1" if fps else ""
            if raw:
                fmt = f",format={s.get_string('format')}" if s.has_field("format") else ""
                best = f"video/x-raw{fmt},width={width},height={height}{fps_text}"
            else:
                best = f"image/jpeg,width={width},height={height}{fps_text}"
    return best


def camera_source(device: Device | None, key: str) -> str:
    """Parte de la tubería que da imagen de la cámara, ya en vídeo sin comprimir."""
    if key == TEST_CAMERA:
        return "videotestsrc is-live=true pattern=smpte ! video/x-raw,width=1280,height=720,framerate=30/1"
    api, _, ident = key.partition(":")
    if api == "pipewire":
        return f"pipewiresrc target-object={quote(ident)} do-timestamp=true ! videoconvert"
    fmt = camera_format(device.caps) if device else ""
    src = f"v4l2src device={quote(ident)} do-timestamp=true"
    if fmt.startswith("image/jpeg"):
        return f"{src} ! {fmt} ! jpegdec"
    if fmt:
        return f"{src} ! {fmt}"
    return f"{src} ! decodebin"


def audio_source(key: str) -> str:
    """pulsesrc del micrófono elegido (o del sonido del sistema)."""
    # El reloj de la tubería es el del sistema (el de la pantalla y la cámara); el sonido se
    # ajusta a él. Si el reloj fuera el de la tarjeta de sonido, el vídeo perdería el principio.
    pulse = "pulsesrc provide-clock=false"
    if key == TEST_CAMERA:  # micrófono de prueba (pitido)
        return "audiotestsrc is-live=true wave=sine freq=440 volume=0.2"
    if key == MIC_DEFAULT:
        return pulse
    if key == SYSTEM_AUDIO:
        return f"{pulse} device={quote(SYSTEM_AUDIO)}"
    api, _, ident = key.partition(":")
    if api == "pipewire":
        return f"pipewiresrc target-object={quote(ident)}"
    return f"{pulse} device={quote(ident)}"


def find(devices: list[Device], key: str) -> Device | None:
    return next((d for d in devices if d.key == key), None)
