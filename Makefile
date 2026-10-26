# Instalación común (paquete .deb y `sudo make install`).
#
#   make install DESTDIR=/ruta/paquete PREFIX=/usr
#
# El código va a un directorio propio y no a site-packages, así el paquete sigue
# funcionando cuando la distribución actualiza Python.

PREFIX  ?= /usr
SYSCONFDIR ?= /etc
LIBDIR  ?= $(PREFIX)/lib/recon
DOCDIR  ?= $(PREFIX)/share/doc/recon
LICENSE_NAME ?= LICENSE
DESTDIR ?=

PKG = $(DESTDIR)$(LIBDIR)/recon

.PHONY: install uninstall

install:
	install -d "$(PKG)"
	install -m 644 src/recon/*.py "$(PKG)/"
	install -d "$(DESTDIR)$(PREFIX)/bin"
	printf '%s\n' '#!/bin/sh' \
	    'export PYTHONPATH="$(LIBDIR)$${PYTHONPATH:+:$$PYTHONPATH}"' \
	    'exec /usr/bin/python3 -m recon "$$@"' > "$(DESTDIR)$(PREFIX)/bin/recon"
	chmod 755 "$(DESTDIR)$(PREFIX)/bin/recon"
	install -Dm 644 data/applications/recon.desktop "$(DESTDIR)$(PREFIX)/share/applications/recon.desktop"
	install -Dm 644 data/autostart/recon.desktop "$(DESTDIR)$(SYSCONFDIR)/xdg/autostart/recon.desktop"
	install -Dm 644 data/icons/recon.svg "$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/recon.svg"
	install -Dm 644 LICENSE "$(DESTDIR)$(DOCDIR)/$(LICENSE_NAME)"

uninstall:
	rm -rf "$(DESTDIR)$(LIBDIR)" "$(DESTDIR)$(DOCDIR)"
	rm -f "$(DESTDIR)$(PREFIX)/bin/recon" \
	      "$(DESTDIR)$(PREFIX)/share/applications/recon.desktop" \
	      "$(DESTDIR)$(SYSCONFDIR)/xdg/autostart/recon.desktop" \
	      "$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/recon.svg"
