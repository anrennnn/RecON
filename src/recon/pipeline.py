"""Monta la tubería de GStreamer de un trozo de grabación.

    pantalla ─ escalar ─┐
                        ├─ compositor ─ H.264 ─┐
    cámara ─ círculo ───┘                      ├─ Matroska (.mkv)
    micrófono ─┐                               │
               ├─ mezclador ─ Opus ────────────┘
    sistema ───┘

La burbuja de la cámara se pinta dentro del vídeo (no es una ventana encima de
la pantalla), así sale igual en cualquier escritorio, también al grabar una
sola ventana. Matroska se puede leer aunque la grabación se corte de golpe.
"""

from dataclasses import dataclass, field

from . import gst
from .gst import quote

BUBBLE_SIZES = {"s": 0.20, "m": 0.27, "l": 0.36}


@dataclass
class Spec:
    location: str
    fps: int = 30
    size: tuple[int, int] = (1920, 1080)        # tamaño final del vídeo
    screen: str = ""                            # fuente de pantalla (sin la parte de escalar)
    prescale: tuple[int, int] | None = None     # escalar la pantalla a esto antes de recortar
    crop: tuple[int, int, int, int] | None = None  # izquierda, arriba, derecha, abajo (píxeles)
    camera: str = ""                            # fuente de la cámara
    camera_full: bool = False                   # solo cámara, a pantalla completa
    bubble: tuple[int, int, int] | None = None  # x, y, diámetro
    mirror: bool = False
    audio: list[str] = field(default_factory=list)  # fuentes de sonido (micrófono primero)
    mic_muted: bool = False


def even(n: float) -> int:
    """Los codificadores de vídeo piden medidas pares."""
    return max(2, int(round(n / 2)) * 2)


def fit(width: int, height: int, max_height: int) -> tuple[int, int]:
    """Tamaño final: como mucho max_height de alto, sin deformar."""
    if max_height and height > max_height:
        width, height = width * max_height / height, max_height
    return even(width), even(height)


def bubble_geometry(size: tuple[int, int], position: str, scale: str) -> tuple[int, int, int]:
    width, height = size
    diameter = even(min(width, height) * BUBBLE_SIZES.get(scale, BUBBLE_SIZES["m"]))
    margin = round(min(width, height) * 0.035)
    vertical, _, horizontal = position.partition("-")
    x = margin if horizontal == "izq" else width - diameter - margin
    y = margin if vertical == "arriba" else height - diameter - margin
    return x, y, diameter


def build(spec: Spec) -> str:
    w, h = spec.size
    fps = spec.fps
    big_queue = "queue max-size-buffers=0 max-size-bytes=0 max-size-time=3000000000"
    parts = [f"matroskamux name=mux ! filesink location={quote(spec.location)}"]

    video_out = (f"videoconvert ! video/x-raw,format=I420 ! {big_queue} ! {gst.h264_encoder(fps)} "
                 "! h264parse ! queue ! mux.")
    flip = "videoflip method=horizontal-flip ! " if spec.mirror else ""

    if spec.screen:
        chain = [spec.screen, "queue name=entrada_pantalla max-size-buffers=4 leaky=downstream", "videoconvert",
                 "videorate",
                 f"video/x-raw,framerate={fps}/1"]
        if spec.prescale:
            chain += ["videoscale", f"video/x-raw,width={spec.prescale[0]},height={spec.prescale[1]}"]
        if spec.crop:
            left, top, right, bottom = spec.crop
            chain.append(f"videocrop left={left} top={top} right={right} bottom={bottom}")
        chain += ["videoscale", f"video/x-raw,width={w},height={h},pixel-aspect-ratio=1/1"]
        if spec.bubble and spec.camera:
            x, y, d = spec.bubble
            parts.append(" ! ".join(chain) + " ! mix.sink_0")
            parts.append(
                f"compositor name=mix background=black sink_0::zorder=0 "
                f"sink_1::zorder=1 sink_1::xpos={x} sink_1::ypos={y} "
                f"! video/x-raw,width={w},height={h},framerate={fps}/1 ! {video_out}"
            )
            parts.append(
                f"{spec.camera} ! queue name=entrada_camara max-size-buffers=4 leaky=downstream ! videoconvert ! {flip}"
                f"aspectratiocrop aspect-ratio=1/1 ! videoscale ! videorate ! videoconvert "
                f"! video/x-raw,format=BGRA,width={d},height={d},framerate={fps}/1,pixel-aspect-ratio=1/1 "
                f"! cairooverlay name=burbuja ! queue max-size-buffers=4 leaky=downstream ! mix.sink_1"
            )
        else:
            parts.append(" ! ".join(chain) + " ! " + video_out)
    elif spec.camera:
        parts.append(
            f"{spec.camera} ! queue name=entrada_camara max-size-buffers=4 leaky=downstream ! videoconvert ! {flip}"
            f"aspectratiocrop aspect-ratio={w}/{h} ! videoscale ! videorate "
            f"! video/x-raw,width={w},height={h},framerate={fps}/1,pixel-aspect-ratio=1/1 ! {video_out}"
        )

    raw_audio = "audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2"
    encode_audio = "audioconvert ! opusenc bitrate=160000 ! queue ! mux."
    mute = " mute=true" if spec.mic_muted else ""
    if len(spec.audio) == 1:
        parts.append(f"{spec.audio[0]} ! queue name=entrada_audio0 ! {raw_audio} ! volume name=micvol{mute} "
                     f"! {encode_audio}")
    elif len(spec.audio) > 1:
        parts.append(f"audiomixer name=amix ! {encode_audio}")
        for n, source in enumerate(spec.audio):
            volume = f" ! volume name=micvol{mute}" if n == 0 else ""
            parts.append(f"{source} ! queue name=entrada_audio{n} ! {raw_audio}{volume} ! queue ! amix.")
    return "  ".join(parts)


def close_inputs(pipe) -> int:
    """Termina el trozo: manda fin de flujo (EOS) justo detrás de cada fuente.

    Mandarlo a la tubería entera depende de que cada fuente lo atienda, y
    pipewiresrc (Wayland) no siempre lo hace. Así el archivo siempre se cierra bien.
    """
    from .gst import Gst

    count = 0
    iterator = pipe.iterate_elements()
    while True:
        result, element = iterator.next()
        if result != Gst.IteratorResult.OK:
            break
        if element.get_name().startswith("entrada_"):
            element.get_static_pad("sink").send_event(Gst.Event.new_eos())
            count += 1
    return count


def draw_bubble(_overlay, cr, _timestamp, _duration, diameter: int):
    """cairooverlay: deja transparente lo que queda fuera del círculo y pinta un borde fino."""
    import cairo

    r = diameter / 2
    cr.set_operator(cairo.OPERATOR_CLEAR)
    cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    cr.rectangle(0, 0, diameter, diameter)
    cr.arc(r, r, r - 1, 0, 6.283185307)
    cr.fill()
    cr.set_operator(cairo.OPERATOR_OVER)
    cr.set_line_width(max(2.0, diameter / 90))
    cr.set_source_rgba(1, 1, 1, 0.85)
    cr.arc(r, r, r - cr.get_line_width() / 2 - 0.5, 0, 6.283185307)
    cr.stroke()
