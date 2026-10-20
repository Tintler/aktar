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

rem Surum bilgisi (F155): src\version.py -> Aktar.exe dosya ozellikleri
py -3 tools\version_info.py build\version_info.txt
if errorlevel 1 (echo HATA: Surum bilgisi uretilemedi. & exit /b 1)

py -3 -m PyInstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name Aktar ^
    --version-file build\version_info.txt ^
    --paths src ^
    %ICON_ARG% ^
    --add-data "bin\ffmpeg.exe;bin" --add-data "bin\ffprobe.exe;bin" ^
    --add-data "assets;assets" ^
    --add-data "translation_prompt.txt;." --add-data "book_translation_prompt.txt;." ^
    --add-data "engines\ema\motor.json;engines\ema" --add-data "engines\voxcpm\motor.json;engines\voxcpm" ^
    --add-data "engines\drama3\motor.json;engines\drama3" ^
    --add-data "web\dist;web\dist" ^
    --exclude-module faster_whisper --exclude-module ctranslate2 --exclude-module sherpa_onnx ^
    --exclude-module PySide6 --exclude-module PyQt5 --exclude-module PyQt6 ^
    --exclude-module numpy --exclude-module setuptools ^
    desktop.py

if errorlevel 1 (
    echo HATA: Derleme basarisiz.
    exit /b 1
)

rem Gomulu oynatici (libmpv, ~120 MB) .exe'ye gomulmez: her acilista acilmasin diye yanina konur.
if exist "bin\libmpv-2.dll" (
    if not exist "dist\bin" mkdir "dist\bin"
    copy /y "bin\libmpv-2.dll" "dist\bin\" >nul
    echo libmpv-2.dll dist\bin\ icine kopyalandi: Aktar.exe ile birlikte bin\ klasorunu da tasiyin.
) else (
    echo UYARI: bin\libmpv-2.dll yok; oynatici WebView ile calisir ^(bkz. bin\README.txt^).
)

echo.
echo Derleme tamamlandi: dist\Aktar.exe
endlocal
