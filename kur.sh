#!/bin/sh
# Aktar kurulum betigi (Linux). Proje klasorunde .venv sanal ortami olusturur ve
# Python paketlerini kurar (Debian/Ubuntu sistem Python'una dogrudan pip ile paket
# kurulmasina izin vermez; bu yuzden sanal ortam kullanilir).
#
# Kullanim:
#   ./kur.sh              arayuz (pywebview + WebKitGTK)
#   ./kur.sh --whisper    + konusmadan metin (faster-whisper, islemcide)
#   ./kur.sh --gpu        + faster-whisper ve NVIDIA CUDA 12 kutuphaneleri (cuBLAS/cuDNN)
#   ./kur.sh --kisayol    + uygulama menusune "Aktar" kisayolu (KDE/GNOME)
# Secenekler birlikte verilebilir. Sistem paketleri (Debian/Ubuntu):
#   sudo apt install python3-venv python3-gi gir1.2-webkit2-4.1 nodejs npm ffmpeg fontconfig \
#                    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
# Pencere WebKitGTK ile acilir (python3-gi sistemden gelir; sanal ortam sistem paketlerini gorur).
# Videolar GStreamer ile oynatilir: H.264/AAC icin gstreamer1.0-libav gerekir.
set -e
cd "$(dirname "$0")"

WHISPER=0
GPU=0
SHORTCUT=0
for arg in "$@"; do
    case "$arg" in
        --whisper) WHISPER=1 ;;
        --gpu) WHISPER=1; GPU=1 ;;
        --kisayol) SHORTCUT=1 ;;
        -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Bilinmeyen secenek: $arg (yardim: ./kur.sh --help)"; exit 2 ;;
    esac
done

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "HATA: $PY bulunamadi. Debian/Ubuntu: sudo apt install python3 python3-venv"
    exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "HATA: Python 3.10 veya ustu gerekli ($("$PY" --version 2>&1))."
    exit 1
fi
if [ ! -x .venv/bin/python ]; then
    echo "Sanal ortam olusturuluyor: .venv"
    if ! "$PY" -m venv --system-site-packages .venv; then
        rm -rf .venv
        echo "HATA: sanal ortam olusturulamadi. Debian/Ubuntu: sudo apt install python3-venv"
        exit 1
    fi
fi

.venv/bin/python -m pip install --upgrade pip
# Linux'ta PyInstaller dahil; pywebview GTK arka ucunu (python3-gi) sistemden kullanir.
.venv/bin/python -m pip install -r requirements.txt
if [ "$WHISPER" = 1 ]; then
    .venv/bin/python -m pip install -r requirements-whisper.txt
fi
if [ "$GPU" = 1 ]; then
    .venv/bin/python -m pip install nvidia-cublas-cu12 'nvidia-cudnn-cu12==9.*'
fi

if [ "$SHORTCUT" = 1 ]; then
    APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$APPS"
    cat > "$APPS/aktar.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Aktar
Comment=Video altyazilarini yerel yapay zeka ile Turkceye cevir, videoya soru sor
Exec="$PWD/baslat.sh" %f
Icon=$PWD/assets/aktar-icon-256.png
Terminal=false
Categories=AudioVideo;Video;Utility;
MimeType=video/x-matroska;video/mp4;video/webm;video/x-msvideo;video/quicktime;
StartupWMClass=Aktar
EOF
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" || true
    echo "Uygulama menusune kisayol eklendi: $APPS/aktar.desktop"
fi

# Eksik sistem bilesenleri icin uyarilar (kurulum yine de tamamlanir).
if ! { [ -x bin/ffmpeg ] && [ -x bin/ffprobe ]; } && \
        ! { command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; }; then
    echo "UYARI: ffmpeg/ffprobe bulunamadi. Kurun: sudo apt install ffmpeg"
fi
if ! command -v fc-list >/dev/null 2>&1; then
    echo "UYARI: fontconfig (fc-list) yok; ASS fontlarinin Turkce kontrolu yapilamaz."
    echo "       Kurun: sudo apt install fontconfig"
fi
if ! .venv/bin/python -c 'import gi; gi.require_version("WebKit2", "4.1")' 2>/dev/null; then
    echo "UYARI: WebKitGTK (python3-gi, gir1.2-webkit2-4.1) bulunamadi; pencere acilmaz."
    echo "       Kurun: sudo apt install python3-gi gir1.2-webkit2-4.1"
    echo "       (Sanal ortam eskiyse silip yeniden kurun: rm -rf .venv && ./kur.sh)"
fi
if ! command -v npm >/dev/null 2>&1; then
    echo "UYARI: npm yok; web arayuzu derlenemez. Kurun: sudo apt install nodejs npm"
fi
if command -v gst-inspect-1.0 >/dev/null 2>&1 && ! gst-inspect-1.0 avdec_h264 >/dev/null 2>&1; then
    echo "UYARI: GStreamer H.264 cozucusu yok; videolar oynatilamayabilir."
    echo "       Kurun: sudo apt install gstreamer1.0-libav gstreamer1.0-plugins-good"
fi

echo
echo "Kurulum tamamlandi. Baslatmak icin: ./baslat.sh"
