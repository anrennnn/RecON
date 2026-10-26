"""Transcribe un vídeo con faster-whisper. Lo lanza RecON con el Python de su entorno
de transcripción (no importa nada de RecON).

    whisper_worker.py vídeo.mp4 --modelo base --modelos DIR [--idioma es]

Escribe vídeo.srt (subtítulos) y vídeo.txt (texto en párrafos) junto al vídeo.
Por la salida estándar avisa del avance: «PROGRESO 0.42».
"""

import argparse
import os
import sys
from pathlib import Path


def timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--modelo", default="base")
    parser.add_argument("--modelos", required=True)
    parser.add_argument("--idioma", default="")
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from faster_whisper import WhisperModel

    video = Path(args.video)
    try:
        # Sin internet: si el modelo ya está descargado, no se intenta conectar.
        model = WhisperModel(args.modelo, device="cpu", compute_type="int8", download_root=args.modelos,
                             local_files_only=True)
    except Exception:  # noqa: BLE001 - aún no descargado
        print("ESTADO Descargando el modelo (solo la primera vez)…", flush=True)
        model = WhisperModel(args.modelo, device="cpu", compute_type="int8", download_root=args.modelos)

    print("ESTADO Transcribiendo…", flush=True)
    segments, info = model.transcribe(str(video), language=args.idioma or None, vad_filter=True,
                                      beam_size=5 if args.modelo != "base" else 1)
    duration = info.duration or 1.0
    srt, paragraphs, current = [], [], []
    last_end = 0.0
    for n, seg in enumerate(segments, 1):
        text = seg.text.strip()
        if not text:
            continue
        srt.append(f"{n}\n{timestamp(seg.start)} --> {timestamp(seg.end)}\n{text}\n")
        # Un párrafo nuevo tras una pausa de más de 1,5 s.
        if current and seg.start - last_end > 1.5:
            paragraphs.append(" ".join(current))
            current = []
        current.append(text)
        last_end = seg.end
        print(f"PROGRESO {min(seg.end / duration, 1.0):.3f}", flush=True)
    if current:
        paragraphs.append(" ".join(current))

    video.with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")
    video.with_suffix(".txt").write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")
    print(f"IDIOMA {info.language}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
