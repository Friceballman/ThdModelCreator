@echo off
setlocal
if not defined MWB_PYTHON set "MWB_PYTHON=C:\AI_test\TripoSR\.venv\Scripts\python.exe"
if not exist "%MWB_PYTHON%" (
    echo Python not found: "%MWB_PYTHON%" 1>&2
    echo Set MWB_PYTHON to the Python executable path. 1>&2
    exit /b 3
)
"%MWB_PYTHON%" -B "%~dp0mwb.py" %*
exit /b %errorlevel%
