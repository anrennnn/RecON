"""Captura de pantalla en Wayland con el portal ScreenCast.

En Wayland ningún programa puede leer la pantalla por su cuenta: se le pide al
escritorio (org.freedesktop.portal.ScreenCast), que pregunta al usuario qué
pantalla o ventana compartir y entrega un flujo de PipeWire. Donde el portal lo
permite (versión 4 o más), RecON guarda el permiso de la pantalla completa para
no volver a preguntar.

Pasos: CreateSession → SelectSources → Start → OpenPipeWireRemote (descriptor
de archivo que se pasa a pipewiresrc). Cada trozo de la grabación (por ejemplo
tras una pausa) pide un descriptor nuevo para la misma sesión.
"""

import secrets

from .gst import GLib

try:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
except (ImportError, ValueError):
    Gio = None

BUS_NAME = "org.freedesktop.portal.Desktop"
OBJECT_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST = "org.freedesktop.portal.ScreenCast"

MONITOR, WINDOW = 1, 2
CURSOR_HIDDEN, CURSOR_EMBEDDED = 1, 2
PERSIST_UNTIL_REVOKED = 2


class Stream:
    def __init__(self, node: int, props: dict):
        self.node = node
        self.position = tuple(props.get("position", (0, 0)))
        self.size = tuple(props.get("size", (0, 0)))
        self.source_type = int(props.get("source_type", MONITOR))


class ScreenCast:
    def __init__(self):
        self.bus = None
        self.version = 0
        self.source_types = 0
        self.cursor_modes = 0
        self.session = ""
        self.streams: list[Stream] = []
        self._checked = False

    def available(self) -> bool:
        if Gio is None or GLib is None:
            return False
        if not self._checked:
            self._checked = True
            try:
                self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                self.version = self._property("version")
                self.source_types = self._property("AvailableSourceTypes")
                self.cursor_modes = self._property("AvailableCursorModes")
            except GLib.Error:
                self.bus = None
                self.version = 0
        return self.version > 0

    def _property(self, name: str) -> int:
        reply = self.bus.call_sync(
            BUS_NAME, OBJECT_PATH, "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", (SCREENCAST, name)), GLib.VariantType.new("(v)"),
            Gio.DBusCallFlags.NONE, 2000, None,
        )
        return int(reply.unpack()[0])

    # --- sesión -------------------------------------------------------------------

    def start(self, kind: str, restore_token: str, done):
        """Pide al usuario la pantalla (kind='pantalla') o ventana ('ventana').

        done(ok, mensaje, nuevo_restore_token). Si ok, self.streams tiene el flujo.
        """
        if not self.available():
            done(False, "El escritorio no ofrece el portal de captura de pantalla (xdg-desktop-portal).", "")
            return
        self.close()
        self._done = done
        self._kind = kind
        self._restore = restore_token
        options = {"session_handle_token": GLib.Variant("s", _token())}
        self._request("CreateSession", "(a{sv})", lambda t: ({**options, "handle_token": t},), self._created)

    def _created(self, results):
        self.session = str(results.get("session_handle", ""))
        if not self.session:
            self._finish(False, "El portal no abrió la sesión de captura.")
            return
        wanted = WINDOW if self._kind == "ventana" else MONITOR
        if self.source_types and not self.source_types & wanted:
            wanted = MONITOR
        options = {"types": GLib.Variant("u", wanted), "multiple": GLib.Variant("b", False)}
        if self.cursor_modes & CURSOR_EMBEDDED:
            options["cursor_mode"] = GLib.Variant("u", CURSOR_EMBEDDED)
        # El permiso solo se guarda para pantallas: cada vez se suele grabar otra ventana.
        if self.version >= 4 and wanted == MONITOR:
            options["persist_mode"] = GLib.Variant("u", PERSIST_UNTIL_REVOKED)
            if self._restore:
                options["restore_token"] = GLib.Variant("s", self._restore)
        self._request("SelectSources", "(oa{sv})", lambda t: (self.session, {**options, "handle_token": t}),
                      self._selected)

    def _selected(self, _results):
        # Aquí el escritorio enseña su ventana para elegir qué compartir.
        self._request("Start", "(osa{sv})", lambda t: (self.session, "", {"handle_token": t}), self._started)

    def _started(self, results):
        self.streams = [Stream(node, dict(props)) for node, props in results.get("streams", [])]
        if not self.streams:
            self._finish(False, "No se eligió nada que grabar.")
            return
        self._finish(True, "", str(results.get("restore_token", "") or ""))

    def _finish(self, ok: bool, message: str, token: str = ""):
        done, self._done = getattr(self, "_done", None), None
        if not ok:
            self.close()
        if done:
            done(ok, message, token)

    def open_remote(self) -> int:
        """Descriptor de archivo de PipeWire para esta sesión (uno por tubería)."""
        reply, fd_list = self.bus.call_with_unix_fd_list_sync(
            BUS_NAME, OBJECT_PATH, SCREENCAST, "OpenPipeWireRemote",
            GLib.Variant("(oa{sv})", (self.session, {})), GLib.VariantType.new("(h)"),
            Gio.DBusCallFlags.NONE, 5000, None, None,
        )
        index = reply.unpack()[0]
        return fd_list.get(index)

    def close(self):
        if self.session and self.bus is not None:
            try:
                self.bus.call_sync(BUS_NAME, self.session, "org.freedesktop.portal.Session", "Close",
                                   None, None, Gio.DBusCallFlags.NONE, 2000, None)
            except GLib.Error:
                pass
        self.session = ""
        self.streams = []

    # --- petición genérica ----------------------------------------------------------

    def _request(self, method: str, signature: str, make_args, on_success):
        """Llama a un método del portal y espera su señal Response."""
        handle = _token()
        sender = self.bus.get_unique_name().lstrip(":").replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{handle}"
        subscription = None

        def on_response(_conn, _sender, _path, _iface, _signal, params):
            self.bus.signal_unsubscribe(subscription)
            code, results = params.unpack()
            if code == 0:
                on_success(results)
            elif code == 1:
                self._finish(False, "")  # el usuario canceló: sin aviso
            else:
                self._finish(False, "El escritorio no permitió grabar la pantalla.")

        # Hay que suscribirse antes de llamar, o la respuesta podría llegar antes.
        subscription = self.bus.signal_subscribe(
            BUS_NAME, "org.freedesktop.portal.Request", "Response", path, None,
            Gio.DBusSignalFlags.NONE, on_response,
        )
        args = make_args(GLib.Variant("s", handle))

        def on_called(bus, result):
            try:
                bus.call_finish(result)
            except GLib.Error as exc:
                self.bus.signal_unsubscribe(subscription)
                self._finish(False, f"El portal falló ({method}): {exc.message}")

        self.bus.call(
            BUS_NAME, OBJECT_PATH, SCREENCAST, method, GLib.Variant(signature, args),
            None, Gio.DBusCallFlags.NONE, -1, None, on_called,
        )


def _token() -> str:
    return "recon_" + secrets.token_hex(6)
