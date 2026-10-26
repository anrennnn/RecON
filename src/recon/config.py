"""Rutas, ajustes guardados y datos del escritorio."""

import json
import os
import shutil
import subprocess
from pathlib import Path

APP_ID = "recon"
APP_NAME = "RecON"
VERSION = "0.1.0"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / APP_ID
CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / APP_ID
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache") / APP_ID
SETTINGS_FILE = CONFIG_DIR / "ajustes.json"
SHORTCUTS_MARKER = CONFIG_DIR / "atajos-configurados"
# Trozos de la grabación en curso: si el equipo se apaga a mitad, aquí siguen.
SEGMENTS_DIR = DATA_DIR / "en-curso"
REPLAY_DIR = CACHE_DIR / "repeticion"
THUMBS_DIR = CACHE_DIR / "miniaturas"
WHISPER_DIR = DATA_DIR / "transcripcion"


def videos_dir() -> Path:
    """La carpeta Vídeos del usuario (en su idioma), como dice xdg-user-dir."""
    folder = ""
    if shutil.which("xdg-user-dir"):
        try:
            folder = subprocess.run(["xdg-user-dir", "VIDEOS"], capture_output=True, text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            folder = ""
    path = Path(folder) if folder else Path.home() / "Vídeos"
    # xdg-user-dir devuelve la carpeta personal si no hay carpeta de vídeos.
    if path == Path.home():
        path = Path.home() / "Vídeos"
    return path


def session_type() -> str:
    """'wayland' o 'x11'."""
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return "wayland"
    return "x11"


def desktop() -> str:
    """Escritorio normalizado: gnome, kde, cinnamon, xfce, mate, cosmic, budgie…"""
    raw = (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "").lower()
    for name in ("kde", "cinnamon", "xfce", "mate", "cosmic", "budgie", "pantheon", "lxqt", "gnome",
                 "hyprland", "sway", "niri", "wayfire", "river"):
        if name in raw:
            return name
    # Pop!_OS, Zorin y Ubuntu usan variantes de GNOME ("pop:GNOME", "zorin:GNOME", "ubuntu:GNOME").
    if "unity" in raw:
        return "gnome"
    return raw or "desconocido"


DEFAULTS = {
    "modo": "pantalla_camara",      # pantalla_camara, pantalla, camara
    "fuente": "pantalla",           # pantalla, ventana, area
    "monitor": "",                  # nombre de la pantalla (X11); vacío = la del puntero
    "camara": "",                   # identificador del dispositivo; vacío = ninguna
    "microfono": "predeterminado",  # identificador; vacío = sin micrófono
    "audio_sistema": False,
    "calidad": "1080",              # original, 1080, 720
    "fps": 30,
    "burbuja_posicion": "abajo-izq",
    "burbuja_tamano": "m",          # s, m, l
    "camara_espejo": False,
    "cuenta_atras": 3,
    "reducir_ruido": True,
    "abrir_revision": True,
    "ocultar_barra": False,
    "carpeta": "",                  # vacío = Vídeos/RecON
    "atajos": {},                   # acción → texto de Qt («Meta+Alt+R»); vacío = predeterminados
    "repeticion": False,
    "repeticion_segundos": 30,
    "modelo_transcripcion": "base",
    "idioma_transcripcion": "",     # vacío = detectar
    "permisos_pantalla": {},        # tipo de fuente → restore_token del portal (Wayland)
    "area": [],                     # último área elegida [x, y, ancho, alto]
}


class Settings:
    """Ajustes en ~/.config/recon/ajustes.json. Se leen y guardan enteros."""

    def __init__(self):
        self.data = dict(DEFAULTS)
        try:
            stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULTS and type(value) is type(DEFAULTS[key]):
                    self.data[key] = value

    def __getitem__(self, key):
        return self.data[key]

    def set(self, key, value, save: bool = True):
        self.data[key] = value
        if save:
            self.save()

    def update(self, values: dict):
        self.data.update(values)
        self.save()

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)

    def output_dir(self) -> Path:
        folder = Path(self.data["carpeta"]).expanduser() if self.data["carpeta"] else videos_dir() / APP_NAME
        folder.mkdir(parents=True, exist_ok=True)
        return folder
