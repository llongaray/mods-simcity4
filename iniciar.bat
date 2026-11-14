@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if errorlevel 1 (echo ERRO: instale Python 3.10+ e marque Add to PATH.& pause& exit /b 1)
)
call ".venv\Scripts\activate.bat"
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (echo Falha ao instalar dependencias.& pause& exit /b 1)
echo.
echo Gerenciador SimCity 2013: http://127.0.0.1:5000
python app.py
pause
