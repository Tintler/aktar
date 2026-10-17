@echo off
rem Aktar konusmadan metin paketi (aktar-whisper) derleme betigi (Windows).
rem Aktar.exe faster-whisper icermez; bu paket ayri derlenir ve Aktar.exe'nin
rem yanina konur (ffmpeg'in bin\ icinde durmasi gibi).
rem Gereksinim: py -3 -m pip install -r requirements.txt -r requirements-whisper.txt
rem GPU (NVIDIA) icin derlemeden ONCE: py -3 -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.*
rem Cikti: dist\aktar-whisper\  ->  bu klasoru Aktar.exe ile ayni klasore koyun.
rem --noupx: UPX, CUDA/ctranslate2 DLL'lerini ve bazi .pyd dosyalarini bozabiliyor.
rem Dislanan moduller (torch, transformers, pandas...) faster-whisper icin gerekmez;
rem ctranslate2'nin istege bagli donusturucu importlari yuzunden pakete siziyorlardi.
setlocal
cd /d "%~dp0"

py -3 -c "import faster_whisper" 2>nul
if errorlevel 1 (
    echo HATA: faster-whisper kurulu degil. Once: py -3 -m pip install -r requirements-whisper.txt
    exit /b 1
)

set "GPU_ARGS="
rem Yalnizca import yetmez: pip kaldirmasindan bos klasorler kalabiliyor; DLL'ler aranir.
py -3 -c "import sys, pathlib, nvidia.cublas as a, nvidia.cudnn as b; sys.exit(0 if all(any(pathlib.Path(p, 'bin').glob('*.dll')) for m in (a, b) for p in m.__path__) else 1)" 2>nul
if not errorlevel 1 set "GPU_ARGS=--collect-binaries nvidia.cublas --collect-binaries nvidia.cudnn"
if defined GPU_ARGS (
    echo NVIDIA CUDA kutuphaneleri pakete eklenecek: GPU destekli paket.
) else (
    echo Bilgi: nvidia-cublas-cu12 / nvidia-cudnn-cu12 kurulu degil; paket GPU kutuphanesi icermez.
    echo GPU icin Aktar Ayarlar - "GPU kutuphane klasoru" ile mevcut cuBLAS 12 / cuDNN 9 klasorunuzu gosterin.
)

py -3 -m PyInstaller ^
    --noconfirm --clean --onedir --console --noupx ^
    --name aktar-whisper ^
    --collect-data faster_whisper ^
    --collect-binaries ctranslate2 ^
    --exclude-module PySide6 --exclude-module scipy --exclude-module torch ^
    --exclude-module transformers --exclude-module numba --exclude-module llvmlite ^
    --exclude-module pyarrow --exclude-module pandas --exclude-module matplotlib ^
    --exclude-module PIL --exclude-module sklearn --exclude-module tensorflow ^
    --exclude-module IPython ^
    %GPU_ARGS% ^
    src\whisper_cli.py

if errorlevel 1 (
    echo HATA: Whisper paketi derlenemedi.
    exit /b 1
)

echo.
echo Derleme tamamlandi: dist\aktar-whisper\
echo Bu klasoru Aktar.exe ile ayni klasore koyun (ornek: dist\Aktar.exe + dist\aktar-whisper\).
endlocal
