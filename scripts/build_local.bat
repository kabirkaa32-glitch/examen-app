@echo off
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe tools\fetch_assets.py
if errorlevel 1 goto fail
.venv\Scripts\python.exe tools\pack_renderer.py
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean guard_app.spec
if errorlevel 1 goto fail
echo.
echo SUCCESS: dist\GuardApp\GuardApp.exe
pause
exit /b 0
:fail
echo BUILD FAILED
pause
exit /b 1
