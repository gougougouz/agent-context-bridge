@echo off
rem Portable launcher: run agentlink from a checkout, no pip install needed.
setlocal
set "HERE=%~dp0"
set "AGENTLINK_SRC=%HERE%..\src"

if exist "%HERE%..\.venv\Scripts\python.exe" (
  set "PYTHON=%HERE%..\.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)

where %PYTHON% >nul 2>nul
if errorlevel 1 (
  echo agentlink: python not found on PATH. 1>&2
  echo   install Python 3.9+ or run: winget install Python.Python.3.12 1>&2
  exit /b 1
)

set "PYTHONPATH=%AGENTLINK_SRC%;%PYTHONPATH%"
"%PYTHON%" -m agentlink %*
exit /b %ERRORLEVEL%