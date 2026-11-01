@echo off
rem Portable launcher: run agentlink from an install dir or a checkout, no pip install.
setlocal
set "HERE=%~dp0"
set "AGENTLINK_SRC=%HERE%..\src"
set "MARKER=%HERE%..\.agentlink-python"
set "PYTHON="

rem the installer records the interpreter it actually used (py -3, python3, ...)
if exist "%MARKER%" set /p PYTHON=<"%MARKER%"
if not defined PYTHON if exist "%HERE%..\.venv\Scripts\python.exe" set "PYTHON=%HERE%..\.venv\Scripts\python.exe"
if not defined PYTHON set "PYTHON=python"

"%PYTHON%" -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo agentlink: Python 3.9+ not found ^(tried "%PYTHON%"^). 1>&2
  echo   install Python and re-run the installer, or write its full path into 1>&2
  echo   %MARKER% 1>&2
  exit /b 1
)

set "PYTHONPATH=%AGENTLINK_SRC%;%PYTHONPATH%"
"%PYTHON%" -m agentlink %*
exit /b %ERRORLEVEL%
