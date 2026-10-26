"""Atajos globales de RecON, al estilo de la Xbox Game Bar (Win+Alt+R…).

En Linux cada escritorio guarda sus atajos en un sitio distinto, así que se
registra un comando por acción («recon grabar», «recon pausa»…) en GNOME,
Cinnamon, XFCE y KDE Plasma. En los gestores en mosaico se indica qué línea
añadir. Los atajos se guardan como texto de Qt («Meta+Alt+R»); Meta es la
tecla Super (la de Windows).
"""

import ast
import shutil
import subprocess

from . import config

# acción → (descripción, atajo predeterminado). El comando es «recon <acción>».
ACTIONS = {
    "grabar": ("Empezar o detener la grabación", "Meta+Alt+R"),
    "pausa": ("Pausar o seguir grabando", "Meta+Alt+P"),
    "micro": ("Silenciar o activar el micrófono", "Meta+Alt+M"),
    "repeticion": ("Guardar los últimos segundos", "Meta+Alt+G"),
    "abrir": ("Abrir RecON", "Meta+Alt+O"),
}

_KEYSYMS = {
    ".": "period", ",": "comma", ";": "semicolon", "/": "slash", "-": "minus", "=": "equal",
    "Space": "space", "Return": "Return", "Enter": "Return", "Tab": "Tab", "Ins": "Insert", "Del": "Delete",
    "Home": "Home", "End": "End", "PgUp": "Prior", "PgDown": "Next", "Esc": "Escape", "Print": "Print",
}
_GTK_MODS = {"Meta": "<Super>", "Ctrl": "<Control>", "Alt": "<Alt>", "Shift": "<Shift>"}


def command(action: str) -> str:
    return f"recon {action}"


def current() -> dict[str, str]:
    """acción → atajo, con los cambios del usuario."""
    saved = config.Settings()["atajos"]
    return {action: saved.get(action, default) for action, (_, default) in ACTIONS.items()}


def split(key: str) -> tuple[list[str], str]:
    if key.endswith("++"):
        return [m for m in key[:-2].split("+") if m], "+"
    *mods, last = key.split("+")
    return mods, last


def keysym(name: str) -> str:
    if name in _KEYSYMS:
        return _KEYSYMS[name]
    return name.lower() if len(name) == 1 else name


def to_gtk(key: str) -> str:
    mods, name = split(key)
    return "".join(_GTK_MODS.get(m, "") for m in mods) + keysym(name)


def label(key: str) -> str:
    """Para enseñar al usuario: «Meta+Alt+R» → «Super+Alt+R»."""
    if not key:
        return "sin atajo"
    mods, name = split(key)
    return "+".join([*("Super" if m == "Meta" else m for m in mods), name])


def _run(*cmd) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _gsettings_list(schema: str, key: str) -> list[str]:
    raw = _run("gsettings", "get", schema, key).removeprefix("@as ")
    try:
        return list(ast.literal_eval(raw)) if raw else []
    except (ValueError, SyntaxError):
        return []


def _gsettings_set(schema: str, key: str, value):
    if isinstance(value, list):
        value = "[" + ", ".join(repr(v) for v in value) + "]"
    _run("gsettings", "set", schema, key, value)


# --- GNOME (Ubuntu, Zorin, Pop!_OS, Fedora) -----------------------------------------

GNOME_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"


def _need_gsettings():
    if not shutil.which("gsettings"):
        raise ShortcutError("No se encontró gsettings; asigna los atajos en los ajustes de teclado del escritorio.")


def _setup_gnome(keys: dict[str, str], _old: dict[str, str]) -> list[str]:
    _need_gsettings()
    paths = [p for p in _gsettings_list(GNOME_KEYS, "custom-keybindings") if "/recon-" not in p]
    for action, key in keys.items():
        if not key:
            continue
        path = f"{GNOME_BASE}recon-{action}/"
        paths.append(path)
        schema = f"{GNOME_KEYS}.custom-keybinding:{path}"
        _gsettings_set(schema, "name", f"RecON: {ACTIONS[action][0]}")
        _gsettings_set(schema, "command", command(action))
        _gsettings_set(schema, "binding", to_gtk(key))
    _gsettings_set(GNOME_KEYS, "custom-keybindings", paths)
    return []


# --- Cinnamon (Linux Mint) ---------------------------------------------------------

CINNAMON_KEYS = "org.cinnamon.desktop.keybindings"
CINNAMON_BASE = "/org/cinnamon/desktop/keybindings/custom-keybindings/"


def _setup_cinnamon(keys: dict[str, str], _old: dict[str, str]) -> list[str]:
    _need_gsettings()
    names = [n for n in _gsettings_list(CINNAMON_KEYS, "custom-list") if not n.startswith("custom-recon-")]
    for action, key in keys.items():
        if not key:
            continue
        slug = f"custom-recon-{action}"
        names.append(slug)
        schema = f"{CINNAMON_KEYS}.custom-keybinding:{CINNAMON_BASE}{slug}/"
        _gsettings_set(schema, "name", f"RecON: {ACTIONS[action][0]}")
        _gsettings_set(schema, "command", command(action))
        _gsettings_set(schema, "binding", [to_gtk(key)])
    _gsettings_set(CINNAMON_KEYS, "custom-list", names)
    return []


# --- XFCE (Xubuntu, MX Linux) ------------------------------------------------------


def _setup_xfce(keys: dict[str, str], _old: dict[str, str]) -> list[str]:
    if not shutil.which("xfconf-query"):
        raise ShortcutError("No se encontró xfconf-query; asigna los atajos en Configuración → Teclado.")
    # Quita los nuestros (por comando, sea cual sea la tecla) y pone los nuevos.
    listing = _run("xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-l", "-v")
    ours = {command(a) for a in ACTIONS}
    for line in listing.splitlines():
        prop, _, value = line.partition(" ")
        if value.strip() in ours:
            _run("xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p", prop, "-r")
    for action, key in keys.items():
        if key:
            _run("xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p", f"/commands/custom/{to_gtk(key)}",
                 "-n", "-t", "string", "-s", command(action))
    return []


# --- KDE Plasma --------------------------------------------------------------------


def _kde_code(key: str) -> int:
    from .qt import QKeySequence, combined

    return combined(QKeySequence(key))


def _kglobalaccel_set(component: str, action: str, keys: list[int]) -> bool:
    if not shutil.which("gdbus"):
        return False
    sequences = ", ".join(f"([{k}, 0, 0, 0],)" for k in keys)
    try:
        subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.kde.kglobalaccel", "--object-path", "/kglobalaccel",
             "--method", "org.kde.KGlobalAccel.setForeignShortcutKeys",
             f"['{component}', '{action}', '', '']", f"@a(ai) [{sequences}]"],
            capture_output=True, timeout=5, check=True,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _setup_kde(keys: dict[str, str], _old: dict[str, str]) -> list[str]:
    # Cada acción es una «Desktop Action» de recon.desktop; kglobalaccel las conoce por su nombre.
    if all(_kglobalaccel_set(f"{config.APP_ID}.desktop", action, [_kde_code(k)] if k else [])
           for action, k in keys.items()):
        return []
    writer = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    if not writer:
        raise ShortcutError("No se pudo hablar con KDE; asigna los atajos en Preferencias del sistema → Atajos.")
    for action, key in keys.items():
        _run(writer, "--file", "kglobalshortcutsrc", "--group", "services", "--group",
             f"{config.APP_ID}.desktop", "--key", action, key or "none")
    return ["Cierra sesión y vuelve a entrar para activar los atajos en KDE Plasma."]


class ShortcutError(RuntimeError):
    pass


SETUP = {"gnome": _setup_gnome, "cinnamon": _setup_cinnamon, "xfce": _setup_xfce, "kde": _setup_kde}


def _manual_lines(desktop: str, keys: dict[str, str]) -> tuple[str, list[str]] | None:
    lines = []
    for action, key in keys.items():
        if not key:
            continue
        mods, name = split(key)
        sym = keysym(name)
        if desktop == "hyprland":
            hypr = " ".join({"Meta": "SUPER", "Ctrl": "CTRL", "Alt": "ALT", "Shift": "SHIFT"}[m] for m in mods)
            lines.append(f"bind = {hypr}, {sym}, exec, {command(action)}")
        elif desktop == "sway":
            sway = "+".join({"Meta": "Mod4", "Ctrl": "Ctrl", "Alt": "Mod1", "Shift": "Shift"}[m] for m in mods)
            lines.append(f"bindsym {sway}+{sym} exec {command(action)}")
        elif desktop == "niri":
            niri = "+".join({"Meta": "Mod", "Ctrl": "Ctrl", "Alt": "Alt", "Shift": "Shift"}[m] for m in mods)
            lines.append(f'{niri}+{sym} {{ spawn "recon" "{action}"; }}')
        else:
            return None
    files = {"hyprland": "~/.config/hypr/hyprland.conf", "sway": "~/.config/sway/config",
             "niri": "~/.config/niri/config.kdl (dentro de binds { })"}
    return files[desktop], lines


def apply(keys: dict[str, str], old: dict[str, str] | None = None) -> list[str]:
    """Pone estos atajos en el escritorio. Devuelve mensajes para el usuario."""
    desktop = config.desktop()
    func = SETUP.get(desktop)
    if func is not None:
        try:
            notes = [f"Atajos listos: {label(keys.get('grabar', ''))} empieza y detiene la grabación.",
                     *func(keys, old or {})]
        except ShortcutError as exc:
            notes = [str(exc)]
    elif (manual := _manual_lines(desktop, keys)) is not None:
        path, lines = manual
        notes = [f"Añade estas líneas a {path}:", *lines]
    else:
        notes = [f"Escritorio «{desktop}» no reconocido. Asigna a mano en sus ajustes de teclado:",
                 *(f"  {label(k)} → {command(a)}" for a, k in keys.items() if k)]
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config.SHORTCUTS_MARKER.write_text(desktop + "\n", encoding="utf-8")
    return notes


def setup_shortcuts(force: bool = False) -> list[str]:
    """Configura los atajos la primera vez (o siempre con force)."""
    if config.SHORTCUTS_MARKER.exists() and not force:
        return []
    return apply(current())


def remove_all():
    """Quita los atajos de RecON del escritorio (al desinstalar con `recon atajos --quitar`)."""
    desktop = config.desktop()
    func = SETUP.get(desktop)
    if func is not None:
        try:
            func({action: "" for action in ACTIONS}, {})
        except ShortcutError:
            pass
    config.SHORTCUTS_MARKER.unlink(missing_ok=True)
