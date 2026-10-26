#!/bin/sh
# Construye dist/recon_<versión>_all.deb (Debian, Ubuntu, Mint, Pop!_OS, Zorin).
set -eu
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' src/recon/config.py)
ROOT=build/recon_${VERSION}_all
rm -rf "$ROOT"
mkdir -p "$ROOT/DEBIAN" dist

make --no-print-directory install DESTDIR="$ROOT" LICENSE_NAME=copyright
find "$ROOT" -name __pycache__ -prune -exec rm -rf {} +

cp packaging/DEBIAN/postinst packaging/DEBIAN/postrm "$ROOT/DEBIAN/"
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"
SIZE=$(du -sk "$ROOT" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" packaging/DEBIAN/control > "$ROOT/DEBIAN/control"
dpkg-deb --root-owner-group --build "$ROOT" "dist/recon_${VERSION}_all.deb"
