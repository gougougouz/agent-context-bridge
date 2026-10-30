@echo off
rem Portable launcher for agentlink: works from a checkout without pip install.
setlocal
set "HERE=%~dp0"
set "AGENTLINK_SRC=%HERE%..\src"
if exist "D:\PythonEnv\python.exe" (
  set "PYTHON=D:\PythonEnv\python.exe"
) else (
  set "PYTHON=python"
)
set "PYTHONPATH=%AGENTLINK_SRC%;%PYTHONPATH%"
"%PYTHON%" -m agentlink %*
exit /b %ERRORLEVEL%