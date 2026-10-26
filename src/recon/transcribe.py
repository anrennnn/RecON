"""Transcripción y subtítulos sin internet, con faster-whisper (Whisper de OpenAI en local).

faster-whisper no está en los repositorios de Debian ni de Ubuntu, así que se
instala una sola vez, cuando el usuario lo pide, en un entorno propio dentro de
~/.local/share/recon/transcripcion. A partir de ahí todo funciona sin conexión.
El modelo (75 MB el rápido, 480 MB el preciso) se descarga la primera vez que
se usa.

El trabajo lo hace whisper_worker.py con el Python de ese entorno; escribe
«PROGRESO 0.42» para la barra de progreso y deja el .srt y el .txt junto al vídeo.
"""

import sys
from pathlib import Path

from . import config
from .jobs import Job, Step, probe

VENV = config.WHISPER_DIR / "entorno"
MODELS = config.WHISPER_DIR / "modelos"
READY_MARK = config.WHISPER_DIR / "instalado"
WORKER = Path(__file__).resolve().parent / "whisper_worker.py"

MODEL_CHOICES = [("base", "Rápido (base, 75 MB)"), ("small", "Preciso (small, 480 MB)")]
LANGUAGES = [("", "Detectar el idioma"), ("es", "Español"), ("en", "Inglés"), ("pt", "Portugués"),
             ("fr", "Francés"), ("it", "Italiano"), ("de", "Alemán"), ("ca", "Catalán")]


def python() -> Path:
    return VENV / "bin" / "python3"


def venv_available() -> bool:
    """Debian separa ensurepip en el paquete python3-venv."""
    import importlib.util

    return importlib.util.find_spec("ensurepip") is not None


def is_ready() -> bool:
    return READY_MARK.exists() and python().exists()


def install_job(parent=None) -> Job:
    """Crea el entorno e instala faster-whisper (necesita internet esta vez)."""
    config.WHISPER_DIR.mkdir(parents=True, exist_ok=True)
    steps = [
        Step(sys.executable, ["-m", "venv", "--clear", str(VENV)], weight=0.2),
        Step(str(VENV / "bin" / "pip"), ["install", "--disable-pip-version-check", "--no-input", "-q",
                                         "faster-whisper"], weight=1.0),
    ]
    return Job("Instalando la transcripción", steps, parent, lambda: READY_MARK.write_text("1\n"))


def transcribe_job(video: Path, model: str, language: str, parent=None) -> Job:
    MODELS.mkdir(parents=True, exist_ok=True)
    args = [str(WORKER), str(video), "--modelo", model, "--modelos", str(MODELS)]
    if language:
        args += ["--idioma", language]
    step = Step(str(python()), args, probe(video)["duration"])
    return Job("Transcribiendo", [step], parent)


def transcript(video: Path) -> str:
    path = video.with_suffix(".txt")
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def suggested_title(text: str) -> str:
    """Primera frase del vídeo, recortada, como título."""
    sentence = text.strip().replace("\n", " ")
    for end in (". ", "? ", "! "):
        cut = sentence.find(end)
        if 12 < cut < 90:
            sentence = sentence[:cut + 1]
            break
    words = sentence.split()
    title = ""
    for word in words:
        if len(title) + len(word) + 1 > 70:
            title += "…"
            break
        title = f"{title} {word}".strip()
    return title.rstrip(".,;:")
