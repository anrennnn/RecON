"""Ajustes: carpeta, comportamiento, repetición instantánea, transcripción y atajos."""

from pathlib import Path

from . import config, shortcuts, theme, transcribe
from .qt import (
    QFileDialog, QFrame, QKeySequence, QKeySequenceEdit, QProgressBar, QPushButton, QScrollArea, Qt,
    QVBoxLayout, QWidget, pyqtSignal,
)
from .widgets import Combo, Switch, label, row


def _card(parent) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(parent)
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(10)
    return frame, layout


def _switch_row(text: str, hint: str, switch: Switch):
    texts = QVBoxLayout()
    texts.setSpacing(1)
    texts.addWidget(label(text))
    if hint:
        small = label(hint, "hint")
        small.setWordWrap(True)
        texts.addWidget(small)
    layout = row(spacing=12)
    layout.addLayout(texts, 1)
    layout.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
    return layout


class SettingsWindow(QWidget):
    replay_changed = pyqtSignal()
    shortcuts_changed = pyqtSignal(list)  # mensajes para el usuario

    def __init__(self, settings: config.Settings):
        super().__init__()
        self.settings = settings
        self.job = None
        t = theme.current()
        self.setWindowTitle("Ajustes · RecON")
        self.setObjectName("window")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.resize(560, 680)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        content.setObjectName("window")
        scroll.setWidget(content)
        body = QVBoxLayout(content)
        body.setContentsMargins(22, 18, 22, 22)
        body.setSpacing(t.shape.spacing)

        # Grabación.
        body.addWidget(label("Grabación", "section"))
        card, layout = _card(content)
        self.folder_label = label("", "sub")
        self.folder_label.setWordWrap(True)
        folder_btn = QPushButton("Cambiar…")
        folder_btn.clicked.connect(self._choose_folder)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.addWidget(label("Carpeta de las grabaciones"))
        texts.addWidget(self.folder_label)
        folder_row = row(spacing=12)
        folder_row.addLayout(texts, 1)
        folder_row.addWidget(folder_btn)
        layout.addLayout(folder_row)

        self.countdown = Combo()
        for seconds, text in ((0, "Sin cuenta atrás"), (3, "3 segundos"), (5, "5 segundos")):
            self.countdown.addItem(text, seconds)
        self.countdown.set_data(settings["cuenta_atras"])
        self.countdown.currentIndexChanged.connect(
            lambda _i: settings.set("cuenta_atras", int(self.countdown.currentData())))
        layout.addLayout(row(label("Cuenta atrás"), None, self.countdown))

        self.denoise = Switch()
        self.denoise.setChecked(settings["reducir_ruido"])
        self.denoise.toggled.connect(lambda v: settings.set("reducir_ruido", v))
        layout.addLayout(_switch_row("Reducir el ruido del micrófono", "Quita zumbidos y ventiladores al guardar.",
                                     self.denoise))
        self.review = Switch()
        self.review.setChecked(settings["abrir_revision"])
        self.review.toggled.connect(lambda v: settings.set("abrir_revision", v))
        layout.addLayout(_switch_row("Abrir la revisión al terminar", "Para copiar, recortar o exportar enseguida.",
                                     self.review))
        self.hide_bar = Switch()
        self.hide_bar.setChecked(settings["ocultar_barra"])
        self.hide_bar.toggled.connect(lambda v: settings.set("ocultar_barra", v))
        layout.addLayout(_switch_row("Ocultar la barra de control", "Se maneja solo con los atajos y no sale en el "
                                     "vídeo aunque grabes toda la pantalla.", self.hide_bar))
        body.addWidget(card)

        # Repetición instantánea.
        body.addWidget(label("Repetición instantánea", "section"))
        card, layout = _card(content)
        self.replay = Switch()
        self.replay.setChecked(settings["repeticion"])
        self.replay.toggled.connect(self._replay_toggled)
        keys = shortcuts.current()
        layout.addLayout(_switch_row(
            "Grabar siempre los últimos segundos",
            f"Como en la Xbox Game Bar: algo raro pasó en pantalla y {shortcuts.label(keys['repeticion'])} "
            "lo guarda aunque no estuvieras grabando. Usa algo de procesador mientras está activa.",
            self.replay))
        self.replay_seconds = Combo()
        for seconds in (15, 30, 60, 120):
            self.replay_seconds.addItem(f"Últimos {seconds} segundos" if seconds < 60 else
                                        f"Últimos {seconds // 60} minuto" + ("s" if seconds > 60 else ""), seconds)
        self.replay_seconds.set_data(settings["repeticion_segundos"])
        self.replay_seconds.currentIndexChanged.connect(self._replay_seconds)
        layout.addLayout(row(label("Duración"), None, self.replay_seconds))
        body.addWidget(card)

        # Transcripción.
        body.addWidget(label("Transcripción y subtítulos", "section"))
        card, layout = _card(content)
        self.whisper_status = label("", "sub")
        self.whisper_status.setWordWrap(True)
        self.whisper_btn = QPushButton("Instalar")
        self.whisper_btn.setObjectName("primary")
        self.whisper_btn.clicked.connect(self._install_whisper)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.addWidget(label("Whisper en tu equipo, sin internet"))
        texts.addWidget(self.whisper_status)
        whisper_row = row(spacing=12)
        whisper_row.addLayout(texts, 1)
        whisper_row.addWidget(self.whisper_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(whisper_row)
        self.whisper_bar = QProgressBar()
        self.whisper_bar.setRange(0, 0)
        self.whisper_bar.hide()
        layout.addWidget(self.whisper_bar)
        self.model = Combo()
        for key, text in transcribe.MODEL_CHOICES:
            self.model.addItem(text, key)
        self.model.set_data(settings["modelo_transcripcion"])
        self.model.currentIndexChanged.connect(
            lambda _i: settings.set("modelo_transcripcion", self.model.currentData()))
        layout.addLayout(row(label("Modelo"), None, self.model))
        self.language = Combo()
        for key, text in transcribe.LANGUAGES:
            self.language.addItem(text, key)
        self.language.set_data(settings["idioma_transcripcion"])
        self.language.currentIndexChanged.connect(
            lambda _i: settings.set("idioma_transcripcion", self.language.currentData()))
        layout.addLayout(row(label("Idioma"), None, self.language))
        body.addWidget(card)

        # Atajos.
        body.addWidget(label("Atajos de teclado", "section"))
        card, layout = _card(content)
        self.key_edits: dict[str, QKeySequenceEdit] = {}
        for action, (text, _default) in shortcuts.ACTIONS.items():
            edit = QKeySequenceEdit(QKeySequence(keys[action]))
            if hasattr(edit, "setMaximumSequenceLength"):
                edit.setMaximumSequenceLength(1)
            edit.setFixedWidth(170)
            self.key_edits[action] = edit
            layout.addLayout(row(label(text), None, edit))
        reset = QPushButton("Restablecer")
        reset.setObjectName("flat")
        reset.clicked.connect(self._reset_keys)
        apply_btn = QPushButton("Aplicar atajos")
        apply_btn.clicked.connect(self._apply_keys)
        self.keys_note = label("", "hint")
        self.keys_note.setWordWrap(True)
        layout.addWidget(self.keys_note)
        layout.addLayout(row(None, reset, apply_btn))
        body.addWidget(card)

        about = label(f"{config.APP_NAME} {config.VERSION} · Todo se procesa en tu equipo.", "hint")
        about.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(about)
        body.addStretch(1)
        self._refresh()

    def open(self):
        self._refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def _refresh(self):
        folder = str(self.settings.output_dir())
        home = str(Path.home())
        self.folder_label.setText("~" + folder[len(home):] if folder.startswith(home + "/") else folder)
        busy = self.job is not None
        if transcribe.is_ready():
            self.whisper_status.setText("Instalada. Pulsa «Transcribir» en la revisión de cualquier vídeo.")
            self.whisper_btn.hide()
        elif not transcribe.venv_available():
            self.whisper_status.setText("Falta el paquete python3-venv:  sudo apt install python3-venv")
            self.whisper_btn.hide()
        else:
            self.whisper_status.setText("Se descarga una sola vez (unos 300 MB, necesita internet). "
                                        "Después funciona sin conexión.")
            self.whisper_btn.setVisible(not busy)
        self.replay_seconds.setEnabled(self.settings["repeticion"])

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Carpeta de las grabaciones", str(self.settings.output_dir()))
        if folder:
            self.settings.set("carpeta", str(Path(folder)))
            self._refresh()

    def _replay_toggled(self, value: bool):
        self.settings.set("repeticion", value)
        self._refresh()
        self.replay_changed.emit()

    def _replay_seconds(self, _index):
        self.settings.set("repeticion_segundos", int(self.replay_seconds.currentData()))
        self.replay_changed.emit()

    def _install_whisper(self):
        self.job = transcribe.install_job(self)
        self.whisper_btn.hide()
        self.whisper_bar.show()
        self.whisper_status.setText("Instalando… puede tardar unos minutos.")

        def finished(ok: bool, message: str):
            self.job = None
            self.whisper_bar.hide()
            self._refresh()
            if not ok:
                self.whisper_status.setText(f"No se pudo instalar: {message or 'sin conexión'}")
                self.whisper_btn.show()

        self.job.finished.connect(finished)
        self.job.start()

    def _keys(self) -> dict[str, str]:
        from .qt import QKeySequence as KS

        result = {}
        for action, edit in self.key_edits.items():
            seq = edit.keySequence()
            result[action] = seq.toString(KS.SequenceFormat.PortableText) if not seq.isEmpty() else ""
        return result

    def _reset_keys(self):
        for action, (_text, default) in shortcuts.ACTIONS.items():
            self.key_edits[action].setKeySequence(QKeySequence(default))
        self._apply_keys()

    def _apply_keys(self):
        keys = self._keys()
        old = shortcuts.current()
        saved = {a: k for a, k in keys.items() if k != shortcuts.ACTIONS[a][1]}
        self.settings.set("atajos", saved)
        notes = shortcuts.apply(keys, old)
        self.keys_note.setText("\n".join(notes))
        self.shortcuts_changed.emit(notes)

