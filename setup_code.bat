@echo off
setlocal
cd /d "%~dp0"

set "PY=%~dp0python\python.exe"
set "TMPCODE=%TEMP%\ov_setup_code.txt"

echo.
echo  ============================================
echo   Open Vending - setup code for a new PC
echo  ============================================
echo.

if not exist "%PY%" (
    echo  [ERROR] Python not found in this folder.
    echo          Run setup.bat first.
    echo.
    pause
    exit /b 1
)

"%PY%" "%~dp0tools\make_setup_code.py" --out "%TMPCODE%"
if errorlevel 1 goto :fail
if not exist "%TMPCODE%" goto :fail

REM Straight to the clipboard - the code is ~750 characters and selecting it
REM out of a console window by hand is how it gets truncated.
type "%TMPCODE%" | clip
del "%TMPCODE%"

echo.
echo  ============================================
echo   Copied to the clipboard.
echo  ============================================
echo.
echo  Paste it into the "Setup code" box on the new PC's welcome
echo  screen, the first time the app runs.
echo.
pause
exit /b 0

:fail
if exist "%TMPCODE%" del "%TMPCODE%"
echo.
echo  [ERROR] Could not generate the code - see the message above.
echo.
pause
exit /b 1
