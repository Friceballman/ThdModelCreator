@echo off
setlocal
if not defined MWB_PYTHON set "MWB_PYTHON=python"
where "%MWB_PYTHON%" >nul 2>nul
if errorlevel 1 (
    echo Python not found: "%MWB_PYTHON%" 1>&2
    echo Set MWB_PYTHON to the Python executable path. 1>&2
    exit /b 3
)
"%MWB_PYTHON%" -B "%~dp0mwb.py" %*
exit /b %errorlevel%
