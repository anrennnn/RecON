"""Lo que se hace con un vídeo después de grabarlo, todo en local con FFmpeg.

* Terminar la grabación: une los trozos (.mkv) en un MP4 sin volver a codificar
  el vídeo; el sonido pasa a AAC y, si se pide, se limpia de ruido de fondo.
* Recortar el principio y el final sin volver a codificar (instantáneo).
* Quitar silencios: detecta las pausas largas y las corta.
* Exportar para cada destino: WhatsApp (16 MB), correo (25 MB), ligero, GIF,
  solo audio y con subtítulos grabados en la imagen.
"""

import re
import tempfile
from pathlib import Path

from .jobs import Job, Step, ffmpeg_args, probe

AUDIO = ["-c:a", "aac", "-b:a", "160k"]
H264 = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
FASTSTART = ["-movflags", "+faststart"]


def temp_file(prefix: str, suffix: str) -> Path:
    import os

    fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.close(fd)
    return Path(name)


def unique(path: Path) -> Path:
    """path, o «nombre 2.mp4», «nombre 3.mp4»… si ya existe."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} {n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def sibling(src: Path, label: str, suffix: str = ".mp4") -> Path:
    return unique(src.with_name(f"{src.stem} ({label}){suffix}"))


# --- Terminar la grabación ------------------------------------------------------------


def _concat_list(segments: list[Path]) -> Path:
    listing = segments[0].parent / "lista.txt"
    lines = []
    for seg in segments:
        escaped = str(seg).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listing


def _with_silence(segment: Path) -> Path:
    """Copia del trozo con una pista de silencio. Si un trozo no tiene sonido (el micrófono
    tardó en arrancar) y otros sí, unirlos tal cual perdería el sonido de todos."""
    import subprocess

    fixed = segment.with_name(segment.stem + "-silencio.mkv")
    try:
        subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", str(segment),
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "libopus", "-shortest", str(fixed)],
                       capture_output=True, timeout=120, check=True)
    except (OSError, subprocess.SubprocessError):
        return segment
    return fixed


def finalize(segments: list[Path], out: Path, denoise: bool, parent=None, on_success=None) -> Job:
    infos = [probe(s) for s in segments]
    duration = sum(i["duration"] for i in infos)
    has_audio = any(i["audio"] for i in infos)
    if has_audio:
        segments = [s if i["audio"] else _with_silence(s) for s, i in zip(segments, infos)]
    listing = _concat_list(segments)
    args = ["-f", "concat", "-safe", "0", "-i", str(listing), "-map", "0", "-c:v", "copy"]
    if has_audio:
        args += AUDIO
        if denoise:
            # Reducción de ruido suave por FFT: quita el zumbido sin sonar a robot.
            args += ["-af", "afftdn=nr=12:nf=-30:tn=1"]
        # El sonido no se alarga más allá del último fotograma.
        args += ["-shortest"]
    args += [*FASTSTART, str(out)]
    return Job("Guardando la grabación", [Step("ffmpeg", ffmpeg_args(*args), duration)], parent, on_success)


# --- Recortar -------------------------------------------------------------------------


def trim(src: Path, start: float, end: float, out: Path, parent=None, on_success=None) -> Job:
    args = ["-ss", f"{start:.3f}", "-i", str(src), "-t", f"{max(end - start, 0.1):.3f}", "-map", "0",
            "-c", "copy", "-avoid_negative_ts", "make_zero", *FASTSTART, str(out)]
    return Job("Recortando", [Step("ffmpeg", ffmpeg_args(*args), end - start)], parent, on_success)


# --- Quitar silencios -----------------------------------------------------------------

_SILENCE_START = re.compile(r"silence_start: (-?[0-9.]+)")
_SILENCE_END = re.compile(r"silence_end: (-?[0-9.]+)")


def keep_ranges(silences: list[tuple[float, float]], duration: float, pad: float = 0.18) -> list[tuple[float, float]]:
    """Tramos que se quedan, dejando un respiro (pad) a cada lado de cada corte."""
    keep, cursor = [], 0.0
    for start, end in silences:
        cut_from, cut_to = max(start + pad, 0.0), min(end - pad, duration)
        if cut_to - cut_from < 0.25:
            continue
        if cut_from > cursor:
            keep.append((cursor, cut_from))
        cursor = cut_to
    if cursor < duration:
        keep.append((cursor, duration))
    return [(a, b) for a, b in keep if b - a > 0.05]


def remove_silences(src: Path, out: Path, threshold_db: int = -35, min_silence: float = 0.7,
                    parent=None, on_success=None) -> Job:
    info = probe(src)
    duration = info["duration"]
    found: list[tuple[float, float]] = []
    state = {"start": None}
    script = temp_file("recon-silencios-", ".txt")

    def collect(line: str):
        if (m := _SILENCE_START.search(line)):
            state["start"] = max(float(m.group(1)), 0.0)
        elif (m := _SILENCE_END.search(line)) and state["start"] is not None:
            found.append((state["start"], float(m.group(1))))
            state["start"] = None

    # Sin «-loglevel error»: silencedetect escribe lo que encuentra como información.
    detect = Step("ffmpeg", ["-hide_banner", "-nostdin", "-progress", "pipe:1", "-nostats", "-i", str(src),
                             "-vn", "-af", f"silencedetect=noise={threshold_db}dB:d={min_silence}",
                             "-f", "null", "-"],
                  duration, weight=0.25, on_output=collect)

    def prepare(step: Step):
        if state["start"] is not None:  # silencio hasta el final
            found.append((state["start"], duration))
        keep = keep_ranges(found, duration)
        kept = sum(b - a for a, b in keep)
        if not found or duration - kept < 0.5:
            raise RuntimeError("No hay silencios largos que quitar.")
        expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keep)
        script.write_text(
            f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[v];[0:a]aselect='{expr}',asetpts=N/SR/TB[a]",
            encoding="utf-8",
        )
        step.duration = kept
        state["saved"] = duration - kept

    cut = Step("ffmpeg", ffmpeg_args("-i", str(src), "-filter_complex_script", str(script), "-map", "[v]",
                                     "-map", "[a]", *H264, "-crf", "21", *AUDIO, *FASTSTART, str(out)),
               duration, weight=1.0, before=prepare)

    def success():
        script.unlink(missing_ok=True)
        saved = state.get("saved", 0)
        result = on_success() if on_success else ""
        return result or f"Quitados {format_duration(saved)} de silencios."

    return Job("Quitando silencios", [detect, cut], parent, success)


# --- Exportar -------------------------------------------------------------------------

PRESETS = {
    "whatsapp": ("Para WhatsApp (16 MB)", "WhatsApp"),
    "correo": ("Para correo (25 MB)", "correo"),
    "ligero": ("MP4 ligero (720p)", "ligero"),
    "gif": ("GIF animado", "GIF"),
    "audio": ("Solo audio (M4A)", "audio"),
    "subtitulos": ("Con subtítulos en la imagen", "subtitulado"),
}


def _sized(src: Path, megabytes: float, duration: float, has_audio: bool) -> list[str]:
    audio_kbps = 96 if has_audio else 0
    total_kbps = megabytes * 8 * 1024 * 0.93 / max(duration, 1.0)
    # Tope de calidad: un vídeo corto no necesita gastar los 16 MB.
    video_kbps = min(max(int(total_kbps - audio_kbps), 120), 2500)
    height = 720 if video_kbps >= 700 else 540 if video_kbps >= 380 else 360
    args = ["-i", str(src), "-vf", f"scale=-2:'min({height},ih)'", *H264, "-b:v", f"{video_kbps}k",
            "-maxrate", f"{int(video_kbps * 1.25)}k", "-bufsize", f"{video_kbps * 2}k"]
    args += ["-c:a", "aac", "-b:a", f"{audio_kbps}k", "-ac", "2"] if has_audio else ["-an"]
    return [*args, *FASTSTART]


def export(src: Path, preset: str, parent=None, on_success=None) -> tuple[Job, Path]:
    info = probe(src)
    duration = info["duration"]
    label = PRESETS[preset][1]
    if preset == "whatsapp":
        out = sibling(src, label)
        args = _sized(src, 15.5, duration, info["audio"])
    elif preset == "correo":
        out = sibling(src, label)
        args = _sized(src, 24, duration, info["audio"])
    elif preset == "ligero":
        out = sibling(src, label)
        args = ["-i", str(src), "-vf", "scale=-2:'min(720,ih)'", *H264, "-crf", "26",
                *(["-c:a", "aac", "-b:a", "128k"] if info["audio"] else ["-an"]), *FASTSTART]
    elif preset == "gif":
        out = sibling(src, label, ".gif")
        args = ["-i", str(src), "-filter_complex",
                "fps=12,scale='min(800,iw)':-2:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
                "[b][p]paletteuse=dither=bayer:bayer_scale=4", "-loop", "0"]
    elif preset == "audio":
        out = sibling(src, label, ".m4a")
        args = ["-i", str(src), "-vn", *AUDIO]
    elif preset == "subtitulos":
        srt = src.with_suffix(".srt")
        if not srt.exists():
            raise FileNotFoundError("Primero transcribe el vídeo para tener subtítulos.")
        # El filtro subtitles no se lleva bien con comillas y dos puntos en la ruta.
        simple = temp_file("recon-", ".srt")
        simple.write_bytes(srt.read_bytes())
        out = sibling(src, label)
        style = "FontName=Sans,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=2,Shadow=0,MarginV=24"
        args = ["-i", str(src), "-vf", f"subtitles={simple}:force_style='{style}'", *H264, "-crf", "21",
                *(["-c:a", "copy"] if info["audio"] else []), *FASTSTART]
    else:
        raise KeyError(preset)
    job = Job(PRESETS[preset][0], [Step("ffmpeg", ffmpeg_args(*args, str(out)), duration)], parent, on_success)
    return job, out


# --- Utilidades -----------------------------------------------------------------------


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_size(size: int) -> str:
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.1f} GB".replace(".", ",")
    if size >= 1024 ** 2:
        return f"{size / 1024 ** 2:.1f} MB".replace(".", ",")
    return f"{max(size // 1024, 1)} KB"


def thumbnail(src: Path, out: Path, at: float = 1.0, width: int = 640) -> bool:
    import subprocess

    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(src),
             "-frames:v", "1", "-vf", f"scale={width}:-2", str(out)],
            capture_output=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.exists()


def frame_at(src: Path, at: float, width: int = 640) -> bytes:
    """Un fotograma en PNG (para el recorte), sin tocar disco."""
    import subprocess

    try:
        return subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{max(at, 0):.3f}", "-i", str(src),
             "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return b""
