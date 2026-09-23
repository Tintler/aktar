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

py -3 -m PyInstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name Aktar ^
    %ICON_ARG% ^
    --add-data "bin;bin" ^
    --add-data "assets;assets" ^
    --add-data "translation_prompt.txt;." ^
    gui.py

if errorlevel 1 (
    echo HATA: Derleme basarisiz.
    exit /b 1
)

echo.
echo Derleme tamamlandi: dist\Aktar.exe
endlocal
