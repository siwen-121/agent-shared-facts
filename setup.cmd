@echo off
if /i "%~1"=="--install-python" goto install
where py >nul 2>&1
if errorlevel 1 goto python
py -3 "%~dp0setup-devices.py" %*
goto done
:python
where python >nul 2>&1
if errorlevel 1 (
  echo Python 3.12+ required. https://www.python.org/downloads/windows/
  exit /b 1
)
python "%~dp0setup-devices.py" %*
goto done
:install
where winget >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.12+ from https://www.python.org/downloads/windows/
  exit /b 1
)
winget install --id Python.Python.3.12 --exact --source winget
exit /b %errorlevel%
:done
set "result=%errorlevel%"
if "%~1"=="" pause
exit /b %result%
