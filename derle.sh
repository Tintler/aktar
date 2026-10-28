#!/bin/sh
# Aktar tek dosya Linux derleme betigi (DERLE.cmd'nin karsiligi).
# Gereksinim: ./kur.sh  (PyInstaller requirements.txt icinde)
# Cikti: dist/Aktar  (calistirilabilir tek dosya; derlendigi dagitimdan eski
# glibc'li sistemlerde calismayabilir - en eski hedef sistemde derleyin).
# ffmpeg: bin/ffmpeg ve bin/ffprobe (Linux ikilileri) varsa pakete gomulur;
# yoksa calisirken sistemdeki ffmpeg kullanilir (sudo apt install ffmpeg).
# Spec dosyasi build/linux altina yazilir; Windows'un Aktar.spec'i degismez.
set -e
cd "$(dirname "$0")"
ROOT="$PWD"

PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
if ! "$PY" -c 'import PyInstaller' 2>/dev/null; then
    echo "HATA: PyInstaller kurulu degil. Once: ./kur.sh"
    exit 1
fi

# PyInstaller Python paylasimli kutuphanesini (libpython3.X.so) pakete koyar; Debian/Ubuntu
# sistem Python'unda bu ayri bir pakettir.
if ! "$PY" -c 'import ctypes, sysconfig; ctypes.CDLL(sysconfig.get_config_var("INSTSONAME"))' 2>/dev/null; then
    echo "HATA: Python paylasimli kutuphanesi bulunamadi. Debian/Ubuntu: sudo apt install libpython3-dev"
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    echo "HATA: npm yok (web arayuzu derlenemez). Kurun: sudo apt install nodejs npm"
    exit 1
fi
(cd web && npm ci && npm run build)

set -- --add-data "$ROOT/assets:assets" --add-data "$ROOT/translation_prompt.txt:." --add-data "$ROOT/book_translation_prompt.txt:." --add-data "$ROOT/engines/ema/motor.json:engines/ema" --add-data "$ROOT/engines/voxcpm/motor.json:engines/voxcpm"     --add-data "$ROOT/web/dist:web/dist"
if [ -x bin/ffmpeg ] && [ -x bin/ffprobe ]; then
    mkdir -p build/linux/bin
    cp bin/ffmpeg bin/ffprobe build/linux/bin/
    set -- "$@" --add-data "$ROOT/build/linux/bin:bin"
    echo "bin/ffmpeg ve bin/ffprobe pakete gomulecek."
else
    echo "Bilgi: bin/ icinde Linux ffmpeg/ffprobe yok; sistemdeki ffmpeg kullanilacak."
fi

"$PY" -m PyInstaller \
    --noconfirm --clean --onefile --windowed \
    --name Aktar \
    --specpath build/linux --workpath build/linux/work \
    --paths "$ROOT/src" \
    "$@" \
    --exclude-module faster_whisper --exclude-module ctranslate2 --exclude-module sherpa_onnx \
    --exclude-module PySide6 --exclude-module PyQt5 --exclude-module PyQt6 \
    --exclude-module setuptools \
    desktop.py

echo
echo "Derleme tamamlandi: dist/Aktar"
