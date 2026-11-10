@echo off
REM Runs the PCB Inspector test suite on Windows. Extra args go to pytest.
cd /d "%~dp0"
if not "%~1"=="" set "PYTEST_ARGS=%*"
call run.bat --test
exit /b %errorlevel%
