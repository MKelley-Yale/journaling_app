@echo off
REM --- One-click runner for the journaling app (Windows) ---
cd /d %~dp0

if not exist venv (
  echo First run: creating environment and installing dependencies...
  python -m venv venv
  call venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call venv\Scripts\activate.bat
)

echo.
echo Starting journal on http://localhost:8000  (press Ctrl+C to stop)
echo.
python -m uvicorn server:app --host 0.0.0.0 --port 8000
pause
