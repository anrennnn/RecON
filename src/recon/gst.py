"""GStreamer (por PyGObject) y los elementos que RecON necesita.

Qt en Linux corre sobre el bucle de eventos de GLib, así que los mensajes del
bus de GStreamer llegan al hilo principal sin bucles propios.
"""

try:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst

    Gst.init(None)
except (ImportError, ValueError):  # falta python3-gi o gir1.2-gstreamer-1.0
    Gst = GLib = None

# Elemento → paquete de Debian/Ubuntu que lo trae, para avisar si falta.
REQUIRED = {
    "videoconvert": "gstreamer1.0-plugins-base",
    "compositor": "gstreamer1.0-plugins-base",
    "opusenc": "gstreamer1.0-plugins-base",
    "matroskamux": "gstreamer1.0-plugins-good",
    "pulsesrc": "gstreamer1.0-pulseaudio",
    "v4l2src": "gstreamer1.0-plugins-good",
    "cairooverlay": "gstreamer1.0-plugins-good",
    "h264parse": "gstreamer1.0-plugins-bad",
}


def available() -> bool:
    return Gst is not None


def has(element: str) -> bool:
    return Gst is not None and Gst.ElementFactory.find(element) is not None


def missing_packages() -> list[str]:
    if Gst is None:
        return ["gir1.2-gstreamer-1.0"]
    packages = {pkg for element, pkg in REQUIRED.items() if not has(element)}
    if not (has("x264enc") or has("openh264enc")):
        packages.add("gstreamer1.0-plugins-ugly")
    return sorted(packages)


def h264_encoder(fps: int) -> str:
    """Codificador H.264 por software. Fotograma clave cada segundo: así recortar sin
    volver a codificar corta como mucho un segundo antes de lo pedido."""
    if has("x264enc"):
        # pass=qual es calidad constante: el texto de la pantalla se lee nítido.
        return (f"x264enc speed-preset=veryfast tune=zerolatency pass=qual quantizer=22 key-int-max={fps} "
                "threads=0 ! video/x-h264,profile=high")
    return f"openh264enc complexity=low rate-control=quality gop-size={fps} bitrate=12000000"


def quote(value: str) -> str:
    """Valor entre comillas para gst-launch (rutas y nombres de dispositivo)."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
