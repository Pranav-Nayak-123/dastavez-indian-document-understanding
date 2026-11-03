@echo off
rem Starts Dastavez and opens the browser at http://localhost:5050
rem Uses Anaconda's Python if it is installed, otherwise the "python" on PATH.
cd /d "%~dp0"
if exist "%USERPROFILE%\anaconda3\python.exe" (
    "%USERPROFILE%\anaconda3\python.exe" server.py
) else (
    python server.py
)
pause
