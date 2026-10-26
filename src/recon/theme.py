"""Aspecto de RecON según el escritorio, en vez de un diseño fijo.

* Claro u oscuro, color de acento y tipo de letra: los del escritorio.
* Forma: cada familia de escritorios tiene su «estilo». En GNOME (y COSMIC,
  Budgie, Pantheon) los botones son planos y redondeados como en libadwaita;
  en KDE Plasma son más compactos y con borde, como Breeze; en Cinnamon, MATE
  y XFCE, un término medio con bordes; en los gestores en mosaico, esquinas
  pequeñas.
* El rojo de grabar es el rojo de cada escritorio (el de GNOME, el de Breeze…).
"""

import shutil
import subprocess
from dataclasses import dataclass

from . import config
from .qt import QColor, QFont, QGuiApplication

# Acentos de GNOME 47+ (org.gnome.desktop.interface accent-color), con los tonos de libadwaita.
GNOME_ACCENTS = {
    "blue": "#3584e4", "teal": "#2190a4", "green": "#3a944a", "yellow": "#c88800", "orange": "#ed5b00",
    "red": "#e62d42", "pink": "#d56199", "purple": "#9141ac", "slate": "#6f8396",
}
# Palabras en nombres de temas de GTK (Zorin, Mint, Yaru, Pop…) y un tono parecido.
THEME_WORDS = {
    "aqua": "#1f9ede", "teal": "#2190a4", "blue": "#3584e4", "green": "#3a944a", "olive": "#4b8501",
    "sage": "#657b69", "orange": "#e95420", "red": "#e62d42", "magenta": "#b34cb3", "pink": "#d56199",
    "purple": "#9141ac", "grey": "#6f8396", "gray": "#6f8396", "brown": "#986a44", "sand": "#c8ac69",
    "yellow": "#c88800", "viridian": "#03875b", "prussiangreen": "#308280", "bark": "#787859",
    "zorin": "#15a6f0", "yaru": "#e95420", "pop": "#48b9c7",
}
DEFAULT_ACCENT = "#3584e4"
# Qt usa este azul cuando no conoce el acento del sistema (estilo Fusion).
QT_FALLBACK_HIGHLIGHTS = {"#308cc6", "#3daee9"}


@dataclass(frozen=True)
class Shape:
    family: str          # adwaita, breeze, clasico, mosaico
    radius: int          # esquinas de la ventana
    control: int         # esquinas de botones y campos
    bordered: bool       # botones con borde (Breeze, clásico) o planos (libadwaita)
    spacing: int
    control_height: int
    pill_primary: bool   # botón principal en forma de píldora
    red: str             # rojo de grabar


SHAPES = {
    "adwaita": Shape("adwaita", 14, 9, False, 12, 38, True, "#e01b24"),
    "breeze": Shape("breeze", 8, 5, True, 8, 34, False, "#da4453"),
    "clasico": Shape("clasico", 10, 6, True, 10, 36, False, "#e5484d"),
    "mosaico": Shape("mosaico", 6, 4, True, 8, 34, False, "#e5484d"),
}
FAMILY = {
    "gnome": "adwaita", "cosmic": "adwaita", "budgie": "adwaita", "pantheon": "adwaita",
    "kde": "breeze", "lxqt": "breeze",
    "cinnamon": "clasico", "mate": "clasico", "xfce": "clasico",
    "hyprland": "mosaico", "sway": "mosaico", "niri": "mosaico", "wayfire": "mosaico", "river": "mosaico",
}


def _read(*cmd) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.strip("'\"")


def _gnome_like(desktop: str) -> bool:
    return desktop in ("gnome", "cosmic", "budgie", "pantheon", "desconocido") or "gnome" in desktop


def _gtk_theme(desktop: str) -> tuple[str, str]:
    """(tema de GTK, preferencia de color de GNOME)."""
    if desktop == "cinnamon":
        return _read("gsettings", "get", "org.cinnamon.desktop.interface", "gtk-theme"), ""
    if desktop == "xfce":
        return _read("xfconf-query", "-c", "xsettings", "-p", "/Net/ThemeName"), ""
    if desktop == "mate":
        return _read("gsettings", "get", "org.mate.interface", "gtk-theme"), ""
    if _gnome_like(desktop):
        return (
            _read("gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"),
            _read("gsettings", "get", "org.gnome.desktop.interface", "color-scheme"),
        )
    return "", ""


def _desktop_font(desktop: str) -> QFont | None:
    """El tipo de letra de la interfaz («Ubuntu 11», «Cantarell 11»…). En KDE ya lo pone Qt."""
    if desktop == "xfce":
        raw = _read("xfconf-query", "-c", "xsettings", "-p", "/Gtk/FontName")
    elif desktop == "mate":
        raw = _read("gsettings", "get", "org.mate.interface", "font-name")
    elif desktop == "cinnamon" or _gnome_like(desktop):
        raw = _read("gsettings", "get", "org.gnome.desktop.interface", "font-name")
    else:
        raw = ""
    if not raw:
        return None
    name, _, size = raw.rpartition(" ")
    try:
        points = float(size)
    except ValueError:
        name, points = raw, 10.0
    # Quita estilos que GTK pone en el nombre («Inter Medium» no es una familia).
    for word in (" Regular", " Medium", " Semi-Bold", " Bold"):
        name = name.replace(word, "")
    font = QFont(name.strip() or "Sans")
    font.setPointSizeF(max(points, 8.0))
    return font


def close_on_left(desktop: str) -> bool:
    """Si los botones de las ventanas van a la izquierda (elementary, algunos temas de GNOME)."""
    if desktop == "pantheon":
        return True
    if _gnome_like(desktop) or desktop == "cinnamon":
        schema = "org.cinnamon.desktop.wm.preferences" if desktop == "cinnamon" else "org.gnome.desktop.wm.preferences"
        layout = _read("gsettings", "get", schema, "button-layout")
        left, _, _right = layout.partition(":")
        return "close" in left
    return False


def mix(a: QColor, b: QColor, amount: float) -> QColor:
    """amount de a y el resto de b."""
    return QColor(
        round(a.red() * amount + b.red() * (1 - amount)),
        round(a.green() * amount + b.green() * (1 - amount)),
        round(a.blue() * amount + b.blue() * (1 - amount)),
    )


def text_on(color: QColor) -> QColor:
    """Blanco o negro, el que mejor se lea sobre color."""
    r, g, b = (c / 255 for c in (color.red(), color.green(), color.blue()))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return QColor("#ffffff") if lum < 0.62 else QColor("#1a1a1a")


class Theme:
    def __init__(self):
        palette = QGuiApplication.palette()
        window, base, text = palette.window().color(), palette.base().color(), palette.windowText().color()
        palette_dark = window.lightness() < 128

        self.desktop = config.desktop()
        self.shape = SHAPES[FAMILY.get(self.desktop, "adwaita" if _gnome_like(self.desktop) else "clasico")]
        gtk_theme, scheme = ("", "") if self.desktop == "kde" else _gtk_theme(self.desktop)
        if scheme == "prefer-dark":
            dark = True
        elif scheme == "prefer-light":
            dark = False
        elif gtk_theme:
            dark = "dark" in gtk_theme.lower()
        else:
            dark = palette_dark

        if dark == palette_dark and self.desktop in ("kde", "lxqt"):
            # La paleta de Qt ya es la del escritorio.
            self.bg, self.field, self.text = window, base, text
        elif dark:
            self.bg, self.field, self.text = QColor("#242424"), QColor("#2f2f2f"), QColor("#f2f2f2")
            if self.shape.family == "breeze":
                self.bg, self.field = QColor("#202326"), QColor("#292c30")
        else:
            self.bg, self.field, self.text = QColor("#fafafa"), QColor("#ffffff"), QColor("#1e1e1e")
            if self.shape.family == "breeze":
                self.bg, self.field = QColor("#eff0f1"), QColor("#fcfcfc")
        self.dark = dark

        highlight = palette.highlight().color()
        accent = None
        if highlight.name() not in QT_FALLBACK_HIGHLIGHTS:
            accent = highlight
        if _gnome_like(self.desktop):
            name = _read("gsettings", "get", "org.gnome.desktop.interface", "accent-color")
            if name in GNOME_ACCENTS:
                accent = QColor(GNOME_ACCENTS[name])
        if accent is None and gtk_theme:
            lowered = gtk_theme.lower().replace("-", "").replace("_", "")
            for word, color in THEME_WORDS.items():
                if word in lowered:
                    accent = QColor(color)
                    break
        if accent is None and self.desktop == "kde":
            accent = QColor("#3daee9")
        self.accent = accent or QColor(DEFAULT_ACCENT)
        self.accent_text = text_on(self.accent)
        self.red = QColor(self.shape.red)
        if dark:
            self.red = self.red.lighter(112)

        self.sub = mix(self.text, self.bg, 0.62)
        self.faint = mix(self.text, self.bg, 0.38)
        self.border = mix(self.text, self.bg, 0.13 if dark else 0.12)
        self.hover = mix(self.text, self.bg, 0.07)
        self.pressed = mix(self.text, self.bg, 0.12)
        # Botones planos de libadwaita: un velo del color del texto.
        self.button = mix(self.text, self.bg, 0.09 if dark else 0.07)
        self.selected = mix(self.accent, self.bg, 0.24 if dark else 0.16)
        self.font = _desktop_font(self.desktop)
        self.close_left = close_on_left(self.desktop)

    def palette(self):
        """Paleta de Qt con estos colores, para que los diálogos estándar combinen."""
        from .qt import QPalette

        palette = QPalette(QGuiApplication.palette())
        role = QPalette.ColorRole
        for roles, color in (
            ((role.Window, role.Button, role.AlternateBase, role.ToolTipBase), self.bg),
            ((role.Base,), self.field),
            ((role.WindowText, role.Text, role.ButtonText, role.ToolTipText), self.text),
            ((role.Highlight,), self.accent),
            ((role.HighlightedText,), self.accent_text),
            ((role.PlaceholderText,), self.sub),
        ):
            for r in roles:
                palette.setColor(r, color)
        return palette

    def stylesheet(self) -> str:
        s = self.shape
        c = {k: v.name() for k, v in vars(self).items() if isinstance(v, QColor)}
        r, cr = s.radius, s.control
        border = f"1px solid {c['border']}" if s.bordered else "1px solid transparent"
        button_bg = c["field"] if s.bordered else c["button"]
        # Qt no redondea si el radio pasa de la mitad del alto: se queda un píxel por debajo.
        primary_radius = s.control_height // 2 - 1 if s.pill_primary else cr
        record_h = s.control_height + 8
        record_radius = record_h // 2 - 1 if s.pill_primary else cr + 1
        return f"""
            QWidget {{ color: {c['text']}; }}
            #surface {{ background: {c['bg']}; border: 1px solid {c['border']}; border-radius: {r}px; }}
            #window {{ background: {c['bg']}; }}
            QLabel#title {{ font-size: 15px; font-weight: 700; }}
            QLabel#brand {{ font-size: 17px; font-weight: 800; letter-spacing: 0.3px; }}
            QLabel#section {{ color: {c['sub']}; font-weight: 600; font-size: 12px; }}
            QLabel#sub, QLabel#hint {{ color: {c['sub']}; }}
            QLabel#hint {{ font-size: 12px; }}
            QLabel#error {{ color: {c['red']}; }}
            #card {{ background: {c['field']}; border: {border if s.bordered else '1px solid ' + c['border']};
                     border-radius: {cr + 2}px; }}

            QPushButton, QToolButton#button {{
                background: {button_bg}; border: {border}; border-radius: {cr}px;
                padding: 0px 14px; min-height: {s.control_height - 2}px; font-weight: 600; }}
            QPushButton:hover, QToolButton#button:hover {{ background: {c['hover'] if s.bordered else c['pressed']}; }}
            QPushButton:pressed {{ background: {c['pressed']}; }}
            QPushButton:disabled {{ color: {c['faint']}; }}
            QPushButton#primary {{ background: {c['accent']}; color: {c['accent_text']}; border: none;
                                   border-radius: {primary_radius}px; min-height: {s.control_height}px;
                                   max-height: {s.control_height}px; padding: 0px 16px; }}
            QPushButton#primary:hover {{ background: {self.accent.lighter(108).name()}; }}
            QPushButton#record {{ background: {c['red']}; color: #ffffff; border: none; font-size: 15px;
                                  border-radius: {record_radius}px; min-height: {record_h}px; max-height: {record_h}px;
                                  padding: 0px 14px; }}
            QPushButton#record:hover {{ background: {self.red.lighter(110).name()}; }}
            QPushButton#record:disabled {{ background: {c['faint']}; }}
            QPushButton#danger {{ color: {c['red']}; }}
            QPushButton::menu-indicator {{ image: none; width: 0px; }}
            QPushButton#flat {{ background: transparent; border: none; }}
            QPushButton#flat:hover {{ background: {c['hover']}; }}

            QToolButton {{ background: transparent; border: none; border-radius: {cr}px; padding: 4px; }}
            QToolButton:hover {{ background: {c['hover']}; }}
            QToolButton:pressed {{ background: {c['pressed']}; }}
            QToolButton:checked {{ background: {c['selected']}; }}
            QToolButton::menu-indicator {{ image: none; width: 0px; }}

            QComboBox, QLineEdit, QSpinBox {{
                background: {c['field']}; border: 1px solid {c['border']}; border-radius: {cr}px;
                padding: 0px 10px; min-height: {s.control_height - 2}px; }}
            QComboBox {{ padding-right: 30px; }}
            QComboBox:hover {{ border-color: {self.sub.name()}; }}
            QLineEdit:focus {{ border: 2px solid {c['accent']}; padding: 0px 9px; }}
            QComboBox:focus {{ border: 2px solid {c['accent']}; padding: 0px 29px 0px 9px; }}
            QComboBox::drop-down {{ border: none; width: 26px; }}
            QComboBox::down-arrow {{ image: none; }}
            QComboBox QAbstractItemView {{ background: {c['field']}; border: 1px solid {c['border']};
                selection-background-color: {c['selected']}; selection-color: {c['text']}; outline: none;
                padding: 4px; }}
            QLineEdit#titleEdit {{ font-size: 15px; font-weight: 700; background: transparent;
                                   border: 1px solid transparent; padding: 0px 6px; }}
            QLineEdit#titleEdit:hover {{ border: 1px solid {c['border']}; }}
            QLineEdit#titleEdit:focus {{ border: 2px solid {c['accent']}; background: {c['field']}; }}

            QProgressBar {{ background: {c['button']}; border: none; border-radius: 3px; max-height: 6px;
                            min-height: 6px; text-align: center; color: transparent; }}
            QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}

            QScrollArea, QListWidget {{ background: transparent; border: none; outline: none; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 3px; min-height: 30px; }}
            QScrollBar::handle:vertical:hover {{ background: {c['sub']}; }}
            QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page
                {{ background: none; height: 0px; }}

            QMenu {{ background: {c['field']}; color: {c['text']}; border: 1px solid {c['border']};
                     border-radius: {cr}px; padding: 4px; }}
            QMenu::item {{ padding: 6px 16px; border-radius: {max(cr - 2, 3)}px; }}
            QMenu::item:selected {{ background: {c['selected']}; }}
            QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}
            QToolTip {{ background: {c['field']}; color: {c['text']}; border: 1px solid {c['border']};
                        padding: 4px 6px; }}
            QCheckBox {{ spacing: 8px; }}
            QTextEdit {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: {cr}px;
                         padding: 6px; }}
        """


_current: Theme | None = None


def current() -> Theme:
    """El tema de la sesión (se crea la primera vez, con QApplication ya en marcha)."""
    global _current
    if _current is None:
        _current = Theme()
    return _current
