#!/bin/sh
# Aktar konusmadan metin paketi (aktar-whisper) Linux derleme betigi
# (DERLE_WHISPER.cmd'nin karsiligi). Derlenmis Aktar faster-whisper icermez; bu
# paket ayri derlenir ve dist/Aktar'in yanina konur.
# Gereksinim: ./kur.sh --whisper   (GPU icin: ./kur.sh --gpu)
# Cikti: dist/aktar-whisper/  ->  bu klasoru Aktar ile ayni klasore koyun.
# Spec dosyasi build/linux altina yazilir; Windows'un aktar-whisper.spec'i degismez.
set -e
cd "$(dirname "$0")"

PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
if ! "$PY" -c 'import faster_whisper' 2>/dev/null; then
    echo "HATA: faster-whisper kurulu degil. Once: ./kur.sh --whisper"
    exit 1
fi

# PyInstaller Python paylasimli kutuphanesini (libpython3.X.so) pakete koyar; Debian/Ubuntu
# sistem Python'unda bu ayri bir pakettir.
if ! "$PY" -c 'import ctypes, sysconfig; ctypes.CDLL(sysconfig.get_config_var("INSTSONAME"))' 2>/dev/null; then
    echo "HATA: Python paylasimli kutuphanesi bulunamadi. Debian/Ubuntu: sudo apt install libpython3-dev"
    exit 1
fi

# Yalnizca import yetmez: pip kaldirmasindan bos klasorler kalabiliyor; .so dosyalari aranir.
GPU=0
if "$PY" -c "import sys, pathlib, nvidia.cublas as a, nvidia.cudnn as b; sys.exit(0 if all(any(pathlib.Path(p, 'lib').glob('lib*.so*')) for m in (a, b) for p in m.__path__) else 1)" 2>/dev/null; then
    GPU=1
    echo "NVIDIA CUDA kutuphaneleri pakete eklenecek: GPU destekli paket."
else
    echo "Bilgi: nvidia-cublas-cu12 / nvidia-cudnn-cu12 kurulu degil; paket GPU kutuphanesi icermez."
    echo "GPU icin Aktar Ayarlar - \"GPU kutuphane klasoru\" ile mevcut cuBLAS 12 / cuDNN 9 klasorunuzu gosterin."
fi

set --
if [ "$GPU" = 1 ]; then
    set -- --collect-binaries nvidia.cublas --collect-binaries nvidia.cudnn
fi

"$PY" -m PyInstaller \
    --noconfirm --clean --onedir --console --noupx \
    --name aktar-whisper \
    --specpath build/linux --workpath build/linux/work \
    --collect-data faster_whisper \
    --collect-binaries ctranslate2 \
    --exclude-module PySide6 --exclude-module scipy --exclude-module torch \
    --exclude-module transformers --exclude-module numba --exclude-module llvmlite \
    --exclude-module pyarrow --exclude-module pandas --exclude-module matplotlib \
    --exclude-module PIL --exclude-module sklearn --exclude-module tensorflow \
    --exclude-module IPython \
    "$@" \
    src/whisper_cli.py

echo
echo "Derleme tamamlandi: dist/aktar-whisper/"
echo "Bu klasoru Aktar ile ayni klasore koyun (ornek: dist/Aktar + dist/aktar-whisper/)."
