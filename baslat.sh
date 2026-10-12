#!/bin/sh
# Aktar arayuzunu baslatir (Linux; GUI_BASLAT.cmd'nin karsiligi).
# Once ./kur.sh ile kurulum yapin; .venv yoksa sistemdeki python3 kullanilir.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi
exec "$PY" gui.py "$@"
