@echo off
rem ==== OQIDA を自分のPCでビルドする（Windows用）====
rem 必要なもの: Python 3.12 と Inno Setup 6
setlocal
cd /d %~dp0

if not exist .venv (
  py -3.12 -m venv .venv || goto :err
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt pyinstaller || goto :err

pyinstaller --noconfirm --clean --windowed --name OQIDA ^
  --icon assets\oqida.ico --add-data "ui;ui" --add-data "assets;assets" main.py || goto :err

set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
%ISCC% installer\oqida.iss || goto :err

echo.
echo 完成: dist\OQIDA-*-Setup.exe
pause
exit /b 0

:err
echo.
echo ビルドに失敗しました。上のメッセージを確認してください。
pause
exit /b 1
