#!/bin/sh
# Aktar arayuzunu baslatir (Linux; GUI_BASLAT.cmd'nin karsiligi).
# Once ./kur.sh ile kurulum yapin; .venv yoksa sistemdeki python3 kullanilir.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi
# Web arayuzu (Svelte) derlenmemisse ya da kaynak degistiyse derlenir (Node.js gerekir).
if command -v npm >/dev/null 2>&1; then
    if [ ! -d web/node_modules ]; then
        (cd web && npm ci) || exit 1
    fi
    (cd web && npm run build --silent >/dev/null) || exit 1
elif [ ! -f web/dist/index.html ]; then
    echo "HATA: web arayuzu derlenmemis ve npm yok. Kurun: sudo apt install nodejs npm"
    exit 1
fi
exec "$PY" desktop.py "$@"
