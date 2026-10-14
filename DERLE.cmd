@echo off
rem Aktar tek dosya .exe derleme betigi (Windows).
rem Gereksinim: py -3 -m pip install -r requirements.txt  (PyInstaller dahil)
rem ffmpeg/ffprobe ikilileri bin\ icine konmus olmalidir; paketle gomulur.
rem Simge (logo): assets\aktar.ico kullanilir (yoksa uyari verilir).
setlocal
cd /d "%~dp0"

if not exist "bin\ffmpeg.exe" (
    echo HATA: bin\ffmpeg.exe bulunamadi. Once ffmpeg/ffprobe ikililerini bin\ icine koyun.
    exit /b 1
)
if not exist "bin\ffprobe.exe" (
    echo HATA: bin\ffprobe.exe bulunamadi. Once ffmpeg/ffprobe ikililerini bin\ icine koyun.
    exit /b 1
)

set "ICON_ARG="
if exist "assets\aktar.ico" set "ICON_ARG=--icon assets\aktar.ico"
if not defined ICON_ARG echo UYARI: assets\aktar.ico bulunamadi; .exe varsayilan simgeyle derlenecek.

pushd web
call npm ci
if errorlevel 1 (popd & echo HATA: npm ci basarisiz ^(Node.js kurulu mu?^) & exit /b 1)
call npm run build
if errorlevel 1 (popd & echo HATA: Arayuz derlenemedi. & exit /b 1)
popd

py -3 -m PyInstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name Aktar ^
    %ICON_ARG% ^
    --add-data "bin;bin" ^
    --add-data "assets;assets" ^
    --add-data "translation_prompt.txt;." ^
    --add-data "web\dist;web\dist" ^
    --exclude-module faster_whisper --exclude-module ctranslate2 ^
    --exclude-module PySide6 --exclude-module PyQt5 --exclude-module PyQt6 ^
    --exclude-module numpy --exclude-module setuptools ^
    desktop.py

if errorlevel 1 (
    echo HATA: Derleme basarisiz.
    exit /b 1
)

echo.
echo Derleme tamamlandi: dist\Aktar.exe
endlocal
