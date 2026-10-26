"""Proceso de fondo, icono de la bandeja y comandos de RecON.

Un único proceso por usuario tiene el panel listo y atiende los atajos. Cada
atajo lanza un comando corto («recon grabar», «recon pausa»…) que solo envía la
orden por un socket local y termina. Si el proceso de fondo no está corriendo,
el primero que se lance se convierte en él.
"""

import argparse
import os
import shutil
import subprocess
import sys

from . import config
from .qt import QApplication, QLocalServer, QLocalSocket, QTimer, prepare_application

SOCKET_NAME = f"{config.APP_ID}-{os.getuid()}"
COMMANDS = {
    "abrir": "Abrir el panel de RecON",
    "grabar": "Empezar a grabar con lo último elegido, o detener y guardar",
    "detener": "Detener y guardar la grabación",
    "pausa": "Pausar o seguir grabando",
    "micro": "Silenciar o activar el micrófono",
    "repeticion": "Guardar los últimos segundos (repetición instantánea)",
    "biblioteca": "Abrir la biblioteca de grabaciones",
    "ajustes": "Abrir los ajustes",
    "salir": "Cerrar el proceso de fondo",
}


def send_to_daemon(command: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if not sock.waitForConnected(500):
        return False
    sock.write(command.encode() + b"\n")
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def notify(body: str, title: str = config.APP_NAME):
    print(f"{title}: {body}", file=sys.stderr)
    if not shutil.which("notify-send"):
        return
    subprocess.Popen(["notify-send", "--app-name", config.APP_NAME, "--icon", config.APP_ID,
                      "--expire-time", "5000", "--hint", "int:transient:1", title, body])


class Daemon:
    def __init__(self, app: QApplication):
        from . import shortcuts, theme
        from .library import LibraryWindow
        from .panel import Panel
        from .recorder import Recorder
        from .replay import ReplayBuffer
        from .review import ReviewWindow
        from .settings_ui import SettingsWindow

        self.app = app
        self.theme = theme.current()
        app.setPalette(self.theme.palette())
        if self.theme.font is not None:
            app.setFont(self.theme.font)
        app.setStyleSheet(self.theme.stylesheet())

        self.settings = config.Settings()
        self.recorder = Recorder(self.settings)
        self.panel = Panel(self.settings)
        self.review = ReviewWindow(self.settings, notify)
        self.library = LibraryWindow(self.settings)
        self.settings_window = SettingsWindow(self.settings)
        self.replay = ReplayBuffer(self.settings)
        self.shortcuts = shortcuts
        self.control_bar = None
        self.countdown = None
        self.area_picker = None
        self.pending_request = None
        self.recover_jobs = []

        self.panel.record_requested.connect(self.start_recording)
        self.panel.library_requested.connect(lambda: (self.panel.hide(), self.library.open()))
        self.panel.settings_requested.connect(lambda: (self.panel.hide(), self.settings_window.open()))
        self.library.open_requested.connect(lambda path: self.review.open_video(path))
        self.library.record_requested.connect(lambda: (self.library.hide(), self.panel.open()))
        self.review.changed.connect(lambda: self.library.isVisible() and self.library.reload())
        self.review.library_requested.connect(lambda: (self.review.close(), self.library.open()))
        self.settings_window.replay_changed.connect(self.replay.sync)
        self.recorder.ready.connect(self._ready)
        self.recorder.finished.connect(self._finished)
        self.recorder.failed.connect(self._failed)
        self.recorder.state_changed.connect(self._state_changed)
        self.recorder.mic_changed.connect(self._mic_changed)
        self.replay.saved.connect(self._replay_saved)
        self.replay.failed.connect(notify)

        self._setup_tray()

        QLocalServer.removeServer(SOCKET_NAME)
        self.server = QLocalServer()
        self.server.newConnection.connect(self._on_connection)
        if not self.server.listen(SOCKET_NAME):
            print("No se pudo abrir el socket de control:", self.server.errorString(), file=sys.stderr)

        QTimer.singleShot(1500, self._recover)
        QTimer.singleShot(2000, self.replay.sync)

    # --- órdenes ------------------------------------------------------------------

    def _on_connection(self):
        while self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: self._read(c))

    def _read(self, conn):
        while conn.canReadLine():
            self.handle(bytes(conn.readLine()).decode().strip())

    def handle(self, command: str):
        state = self.recorder.state
        if command == "abrir":
            if state in ("recording", "paused") and self.control_bar is not None:
                self.control_bar.show()
                self.control_bar.raise_()
            else:
                self.panel.open()
        elif command == "grabar":
            if state in ("recording", "paused", "pausing"):
                self.recorder.stop()
            elif state in ("preparing", "ready"):
                self._cancel_countdown()
            elif state == "idle":
                self.quick_record()
        elif command == "detener":
            self.recorder.stop()
        elif command == "pausa":
            if state in ("recording", "paused"):
                self.recorder.pause()
        elif command == "micro":
            if state in ("recording", "paused"):
                self.recorder.toggle_mic()
        elif command == "repeticion":
            self.replay.save()
        elif command == "biblioteca":
            self.library.open()
        elif command == "ajustes":
            self.settings_window.open()
        elif command == "salir":
            self.quit()

    def quick_record(self):
        """Atajo de grabar sin abrir el panel: con lo último que se eligió."""
        if not self.panel.cameras and not self.panel.mics:
            self.panel.refresh_devices()
        self.start_recording(self.panel.build_request())

    # --- grabar -------------------------------------------------------------------

    def start_recording(self, request):
        if self.recorder.busy:
            return
        self.replay.suspend(True)
        self.pending_request = request
        if request.uses_screen and request.source == "area":
            from .overlays import AreaPicker
            from .qt import QRect

            saved = self.settings["area"]
            previous = QRect(*saved[:4]) if len(saved) >= 4 else None
            self.area_picker = AreaPicker(previous)
            self.area_picker.picked.connect(self._area_picked)
            self.area_picker.cancelled.connect(lambda: self.replay.suspend(False))
            # Deja que el panel desaparezca antes de oscurecer la pantalla.
            QTimer.singleShot(150, self.area_picker.start)
            return
        # Con «la ventana activa», espera a que el foco vuelva a esa ventana.
        delay = 300 if request.source == "ventana" and not request.window else 50
        QTimer.singleShot(delay, lambda: self.recorder.prepare(request))

    def _area_picked(self, screen_name: str, rect):
        request = self.pending_request
        request.screen_name = screen_name
        request.area = rect
        self.settings.set("area", [rect.x(), rect.y(), rect.width(), rect.height()])
        self.recorder.prepare(request)

    def _ready(self):
        from . import shortcuts
        from .overlays import Countdown

        seconds = int(self.settings["cuenta_atras"])
        if seconds <= 0:
            self._begin()
            return
        keys = shortcuts.current()
        self.countdown = Countdown(seconds, f"{shortcuts.label(keys['grabar'])} para detener  ·  Esc cancela")
        self.countdown.finished.connect(self._begin)
        self.countdown.cancelled.connect(self.recorder.cancel)
        self.countdown.start()

    def _cancel_countdown(self):
        if self.countdown is not None:
            self.countdown.close()
            self.countdown = None
        self.recorder.cancel()

    def _begin(self):
        from . import shortcuts
        from .overlays import ControlBar, screen_rect_for

        self.countdown = None
        self.recorder.record()
        if self.recorder.state != "recording":
            return
        if not self.settings["ocultar_barra"]:
            if self.control_bar is None:
                keys = {a: shortcuts.label(k) for a, k in shortcuts.current().items()}
                self.control_bar = ControlBar(self.recorder, keys)
                self.control_bar.stop_clicked.connect(self.recorder.stop)
                self.control_bar.pause_clicked.connect(self.recorder.pause)
                self.control_bar.mic_clicked.connect(self.recorder.toggle_mic)
                self.control_bar.discard_clicked.connect(self._discard)
            request = self.recorder.request
            area = screen_rect_for(request.screen_name, request.area) if request.source == "area" else None
            self.control_bar.start(area)

    def _mic_changed(self, muted: bool):
        # Con la barra visible ya se ve el icono tachado; si está oculta, se avisa.
        if self.settings["ocultar_barra"]:
            notify("Micrófono silenciado." if muted else "Micrófono activado.")

    def _discard(self):
        self.recorder.cancel()
        notify("Grabación descartada.")

    def _state_changed(self, state: str):
        self._update_tray(state)
        if state == "idle":
            if self.control_bar is not None:
                self.control_bar.finish()
            self.replay.suspend(False)

    def _finished(self, path):
        if self.control_bar is not None:
            self.control_bar.finish()
        if self.settings["abrir_revision"]:
            self.review.open_video(path, fresh=True)
        else:
            from . import files

            files.copy_to_clipboard([path])
            notify(f"Guardada y copiada: {path.name}")
        if self.library.isVisible():
            self.library.reload()

    def _failed(self, message: str):
        if message:
            notify(message)

    def _replay_saved(self, path):
        from . import files

        files.copy_to_clipboard([path])
        notify(f"Guardados los últimos {self.settings['repeticion_segundos']} s y copiados al portapapeles.")
        if self.library.isVisible():
            self.library.reload()

    def _recover(self):
        """Une los trozos de grabaciones que se cortaron (apagón, cierre forzado)."""
        from .recorder import pending_recordings, recover

        for folder in pending_recordings():
            result = recover(folder, self.settings)
            if result is None:
                continue
            job, out = result
            self.recover_jobs.append(job)
            job.finished.connect(lambda ok, _msg, o=out: notify(
                f"Se recuperó una grabación que se cortó: {o.name}" if ok else
                "Hay una grabación cortada que no se pudo recuperar."))
            job.start()

    # --- bandeja ------------------------------------------------------------------

    def _setup_tray(self):
        from .qt import QMenu, QSystemTrayIcon

        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self._tray_icon(False))
        self.tray.setToolTip(config.APP_NAME)
        menu = QMenu()
        self.tray_record = menu.addAction("Grabar")
        self.tray_record.triggered.connect(lambda: self.handle("grabar"))
        self.tray_pause = menu.addAction("Pausar")
        self.tray_pause.triggered.connect(lambda: self.handle("pausa"))
        self.tray_pause.setVisible(False)
        menu.addSeparator()
        menu.addAction("Abrir RecON").triggered.connect(self.panel.open)
        menu.addAction("Guardar los últimos segundos").triggered.connect(self.replay.save)
        menu.addAction("Biblioteca").triggered.connect(self.library.open)
        menu.addAction("Ajustes").triggered.connect(self.settings_window.open)
        menu.addSeparator()
        menu.addAction("Salir").triggered.connect(self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray_menu = menu
        self.tray.show()

    def _tray_activated(self, reason):
        from .qt import QSystemTrayIcon

        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.recorder.state in ("recording", "paused"):
                self.recorder.stop()
            else:
                self.panel.open()

    def _tray_icon(self, recording: bool):
        from .qt import QColor, QIcon, QPainter, QPixmap, QRectF, Qt

        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        red = self.theme.red
        painter.setPen(Qt.PenStyle.NoPen)
        if recording:
            painter.setBrush(red)
            painter.drawEllipse(QRectF(8, 8, 48, 48))
            painter.setBrush(QColor("#ffffff"))
            painter.drawRoundedRect(QRectF(23, 23, 18, 18), 3, 3)
        else:
            from .qt import QPen

            painter.setPen(QPen(QColor("#ffffff") if self.theme.dark else QColor("#2e2e2e"), 5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(8, 8, 48, 48))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(red)
            painter.drawEllipse(QRectF(20, 20, 24, 24))
        painter.end()
        return QIcon(pixmap)

    def _update_tray(self, state: str):
        if self.tray is None:
            return
        active = state in ("recording", "paused", "pausing")
        self.tray.setIcon(self._tray_icon(active))
        self.tray_record.setText("Detener y guardar" if active else "Grabar")
        self.tray_pause.setVisible(active)
        self.tray_pause.setText("Seguir grabando" if state == "paused" else "Pausar")
        self.tray.setToolTip(f"{config.APP_NAME} · grabando" if active else config.APP_NAME)

    def quit(self):
        if self.recorder.state in ("recording", "paused"):
            self.recorder.finished.connect(lambda _p: self.app.quit())
            self.recorder.failed.connect(lambda _m: self.app.quit())
            self.recorder.stop()
            return
        self.replay.stop()
        self.app.quit()


def _prepare_platform():
    # En Wayland, GNOME, KDE y Cinnamon no dejan a una ventana nativa colocarse ni
    # quedarse encima (la barra de control y la cuenta atrás lo necesitan); con
    # XWayland sí. La captura de pantalla sigue yendo por el portal.
    if (
        config.session_type() == "wayland"
        and config.desktop() in ("gnome", "cinnamon", "kde", "budgie")
        and os.environ.get("DISPLAY")
        and "QT_QPA_PLATFORM" not in os.environ
    ):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="recon", description="Graba la pantalla y la webcam, con todo el trabajo posterior en tu equipo.")
    sub = parser.add_subparsers(dest="command")
    for name, text in COMMANDS.items():
        sub.add_parser(name, help=text)
    sub.add_parser("segundo-plano", help="Iniciar solo el proceso de fondo (al iniciar sesión)")
    atajos = sub.add_parser("atajos", help="Volver a poner los atajos en el escritorio")
    atajos.add_argument("--quitar", action="store_true", help="Quitar los atajos de RecON del escritorio")
    sub.add_parser("version", help="Mostrar la versión")
    args = parser.parse_args(argv)

    if args.command == "version":
        print(config.APP_NAME, config.VERSION)
        return 0
    if args.command == "atajos":
        from . import shortcuts

        if args.quitar:
            shortcuts.remove_all()
            print("Atajos de RecON quitados.")
        else:
            for line in shortcuts.setup_shortcuts(force=True):
                print(line)
        return 0

    from . import gst

    command = args.command or "abrir"
    _prepare_platform()
    prepare_application()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(config.APP_ID)
    app.setApplicationDisplayName(config.APP_NAME)
    app.setDesktopFileName(config.APP_ID)
    app.setQuitOnLastWindowClosed(False)

    if command != "segundo-plano" and send_to_daemon(command):
        return 0
    if command == "segundo-plano" and send_to_daemon("ping"):
        return 0  # ya hay uno corriendo
    if command == "salir":
        return 0

    missing = gst.missing_packages()
    if missing:
        text = "Faltan paquetes para grabar: " + " ".join(missing)
        print(text, file=sys.stderr)
        notify(text + "\nInstálalos con: sudo apt install " + " ".join(missing))
        if gst.Gst is None:
            return 1
    if not shutil.which("ffmpeg"):
        notify("Falta FFmpeg para guardar los vídeos: sudo apt install ffmpeg")

    from .shortcuts import setup_shortcuts

    messages = setup_shortcuts()
    daemon = Daemon(app)
    if messages:
        notify("\n".join(messages))
    if command != "segundo-plano":
        QTimer.singleShot(100, lambda: daemon.handle(command))
    return app.exec()
