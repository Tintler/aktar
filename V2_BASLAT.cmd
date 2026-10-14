@echo off
rem Yeni (Svelte) arayuz - v2 gecisi suresince ayri baslatici; 4. asamada GUI_BASLAT.cmd bunun yerini alir.
chcp 65001 >nul
cd /d "%~dp0"
pushd web
if not exist "node_modules" (
  echo Arayuz bagimliliklari kuruluyor ^(ilk calistirma, Node.js gerekir^)...
  call npm ci
  if errorlevel 1 (popd ^& goto :error)
)
call npm run build --silent >nul
if errorlevel 1 (popd ^& goto :error)
popd
py -3 desktop.py %*
if errorlevel 1 pause
exit /b 0

:error
echo ARAYUZ DERLENEMEDI. Node.js kurulu oldugundan emin olun: https://nodejs.org
pause
exit /b 1
