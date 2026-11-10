@echo off
REM PCB Inspector launcher for Windows.
REM
REM   run.bat                 create .venv (first run), install deps, start the app
REM   run.bat --test          install test deps and run the test suite
REM   run.bat --skip-install  start without checking/installing dependencies
REM   run.bat --no-easyocr    skip the optional EasyOCR/PyTorch download
REM
REM Override the interpreter with:  set PYTHON=C:\Python312\python.exe
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "MODE=app"
set "SKIP_INSTALL=0"
set "NO_EASYOCR=0"
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--test"         (set "MODE=test" & shift & goto parse_args)
if /i "%~1"=="-t"             (set "MODE=test" & shift & goto parse_args)
if /i "%~1"=="--skip-install" (set "SKIP_INSTALL=1" & shift & goto parse_args)
if /i "%~1"=="--no-easyocr"   (set "NO_EASYOCR=1" & shift & goto parse_args)
if /i "%~1"=="--help" goto usage
if /i "%~1"=="-h" goto usage
echo Unknown option: %~1  (use --help)
exit /b 2
:usage
findstr /b "REM" "%~f0"
exit /b 0
:args_done

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

if exist "%VENV_PY%" goto venv_ready

REM ---- find a Python >= 3.10 ----
set "BASE_PY="
if defined PYTHON (
    "%PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "BASE_PY=%PYTHON%"
)
if not defined BASE_PY (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "BASE_PY=py -3"
)
if not defined BASE_PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "BASE_PY=python"
)
if not defined BASE_PY (
    echo ERROR: Python 3.10 or newer is required. Install it from https://www.python.org/downloads/
    echo        and tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)
echo ^>^> Creating virtual environment with %BASE_PY% ...
%BASE_PY% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo ERROR: could not create the virtual environment.
    pause
    exit /b 1
)
"%VENV_PY%" -m pip install --upgrade pip >nul

:venv_ready
if "%SKIP_INSTALL%"=="1" goto run

if "%MODE%"=="test" (set "REQ_FILE=requirements-dev.txt") else (set "REQ_FILE=requirements.txt")
set "STAMP=%VENV_DIR%\.%REQ_FILE%.sha256"
"%VENV_PY%" -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "%REQ_FILE%" > "%VENV_DIR%\.digest.tmp"
set /p DIGEST=<"%VENV_DIR%\.digest.tmp"
set "OLD_DIGEST="
if exist "%STAMP%" set /p OLD_DIGEST=<"%STAMP%"
if "%OLD_DIGEST%"=="%DIGEST%" goto run

echo ^>^> Installing dependencies from %REQ_FILE% ...
if "%NO_EASYOCR%"=="1" (
    findstr /v /i /b "easyocr" "%REQ_FILE%" > "%VENV_DIR%\.req-filtered.txt"
    "%VENV_PY%" -m pip install -r "%VENV_DIR%\.req-filtered.txt"
    if errorlevel 1 goto install_failed
) else (
    "%VENV_PY%" -m pip install -r "%REQ_FILE%"
    if errorlevel 1 goto install_failed
    > "%STAMP%" echo %DIGEST%
)
goto run

:install_failed
echo ERROR: dependency installation failed (see messages above).
echo        If pyzbar fails to load later, install the Visual C++ Redistributable 2013 (x64).
pause
exit /b 1

:run
if "%MODE%"=="test" (
    echo ^>^> Running tests ...
    if not defined QT_QPA_PLATFORM set "QT_QPA_PLATFORM=offscreen"
    if not defined PYTEST_ARGS set "PYTEST_ARGS=-q"
    "%VENV_PY%" -m pytest tests !PYTEST_ARGS!
    exit /b !errorlevel!
)
echo ^>^> Starting PCB Inspector ...
"%VENV_PY%" main.py
if errorlevel 1 (
    echo PCB Inspector exited with an error.
    pause
)
exit /b %errorlevel%
