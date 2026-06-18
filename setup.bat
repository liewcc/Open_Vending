@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "LOG=%ROOT%setup.log"
set "PYTHON_DIR=%ROOT%python"
set "BROWSERS_DIR=%ROOT%browsers"
set "PY=%PYTHON_DIR%\python.exe"
set "NODE_DIR=%ROOT%node"
set "NPM=%NODE_DIR%\npm.cmd"
set "NODE_VERSION=20.18.1"
set "NODE_ZIP=node-v%NODE_VERSION%-win-x64.zip"
set "NODE_URL=https://nodejs.org/dist/v%NODE_VERSION%/%NODE_ZIP%"
set "PYTHONNOUSERSITE=1"
set "PYTHONPATH="
set "PYTHON_VERSION=3.12.7"
set "PYTHON_ZIP=python-%PYTHON_VERSION%-embed-amd64.zip"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/%PYTHON_ZIP%"

echo Setup started: %DATE% %TIME% > "%LOG%"

echo.
echo  ============================================
echo   DVends Open Vending - Setup
echo  ============================================
echo.
echo   Log file: %LOG%
echo.

REM Step 1: Python
if exist "%PY%" (
    echo [OK] Python ready, skipping download
    echo [OK] Python ready >> "%LOG%"
    goto :install_pip
)

echo [1/6] Downloading Python %PYTHON_VERSION%...
echo [1/6] Downloading Python >> "%LOG%"
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%ROOT%%PYTHON_ZIP%' -UseBasicParsing" >> "%LOG%" 2>&1
if not exist "%ROOT%%PYTHON_ZIP%" (
    echo [ERROR] Python download failed >> "%LOG%"
    echo [ERROR] Python download failed. See setup.log for details.
    goto :fail
)

echo       Extracting...
powershell -NoProfile -Command "Expand-Archive -Path '%ROOT%%PYTHON_ZIP%' -DestinationPath '%PYTHON_DIR%' -Force" >> "%LOG%" 2>&1
del "%ROOT%%PYTHON_ZIP%"
powershell -NoProfile -Command "(Get-Content '%PYTHON_DIR%\python312._pth') -replace '#import site','import site' | Set-Content '%PYTHON_DIR%\python312._pth'" >> "%LOG%" 2>&1
echo [OK] Python ready
echo [OK] Python extracted >> "%LOG%"

REM Step 2: pip
:install_pip
if exist "%PYTHON_DIR%\Lib\site-packages\pip" (
    echo [OK] pip ready, skipping install
    echo [OK] pip ready >> "%LOG%"
    goto :install_packages
)

echo [2/6] Installing pip...
echo [2/6] Installing pip >> "%LOG%"
powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%ROOT%get-pip.py' -UseBasicParsing" >> "%LOG%" 2>&1
if not exist "%ROOT%get-pip.py" (
    echo [ERROR] pip download failed >> "%LOG%"
    echo [ERROR] pip download failed. See setup.log for details.
    goto :fail
)
"%PY%" "%ROOT%get-pip.py" --no-warn-script-location --isolated -q >> "%LOG%" 2>&1
del "%ROOT%get-pip.py"
echo [OK] pip ready
echo [OK] pip ready >> "%LOG%"

REM Step 3: Python packages
:install_packages
echo [3/6] Installing Python dependencies...
echo [3/6] Installing Python dependencies >> "%LOG%"
"%PY%" -m pip install -r "%ROOT%requirements.txt" --no-warn-script-location --isolated >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] pip install failed >> "%LOG%"
    echo [ERROR] pip install failed. See setup.log for details.
    goto :fail
)
echo [OK] Python dependencies ready
echo [OK] Python dependencies ready >> "%LOG%"

REM Step 4: Chromium
if exist "%BROWSERS_DIR%" (
    echo [OK] Chromium ready, skipping download
    echo [OK] Chromium ready >> "%LOG%"
    goto :install_node
)

echo [4/6] Downloading Chromium browser (approx 150MB)...
echo [4/6] Downloading Chromium >> "%LOG%"
set "PLAYWRIGHT_BROWSERS_PATH=%BROWSERS_DIR%"
"%PY%" -m playwright install chromium >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] Chromium download failed >> "%LOG%"
    echo [ERROR] Chromium download failed. See setup.log for details.
    goto :fail
)
echo [OK] Chromium ready
echo [OK] Chromium ready >> "%LOG%"

REM Step 5: Node.js
:install_node
if exist "%NPM%" (
    echo [OK] Node.js ready, skipping download
    echo [OK] Node.js ready >> "%LOG%"
    goto :npm_install
)

echo [5/6] Downloading Node.js v%NODE_VERSION%...
echo [5/6] Downloading Node.js >> "%LOG%"
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%NODE_URL%' -OutFile '%ROOT%%NODE_ZIP%' -UseBasicParsing" >> "%LOG%" 2>&1
if not exist "%ROOT%%NODE_ZIP%" (
    echo [ERROR] Node.js download failed >> "%LOG%"
    echo [ERROR] Node.js download failed. See setup.log for details.
    goto :fail
)

echo       Extracting...
powershell -NoProfile -Command "Expand-Archive -Path '%ROOT%%NODE_ZIP%' -DestinationPath '%ROOT%node_tmp' -Force" >> "%LOG%" 2>&1
powershell -NoProfile -Command "Move-Item '%ROOT%node_tmp\node-v%NODE_VERSION%-win-x64' '%NODE_DIR%'" >> "%LOG%" 2>&1
rmdir "%ROOT%node_tmp"
del "%ROOT%%NODE_ZIP%"
echo [OK] Node.js ready
echo [OK] Node.js ready >> "%LOG%"

REM Step 6: npm packages
:npm_install
if exist "%ROOT%node_modules\electron" if exist "%ROOT%node_modules\xlsx" (
    echo [OK] npm packages ready, skipping install
    echo [OK] npm packages ready >> "%LOG%"
    goto :done
)

echo [6/6] Installing Electron + xlsx (approx 100MB)...
echo [6/6] npm install >> "%LOG%"
set "PATH=%NODE_DIR%;%PATH%"
pushd "%ROOT%"
"%NPM%" install --no-fund --no-audit >> "%LOG%" 2>&1
popd
if errorlevel 1 (
    echo [ERROR] npm install failed >> "%LOG%"
    echo [ERROR] npm install failed. See setup.log for details.
    goto :fail
)
echo [OK] Electron + xlsx ready
echo [OK] npm install done >> "%LOG%"

:done
echo Setup completed: %DATE% %TIME% >> "%LOG%"

REM Create desktop shortcut (write PS1 to temp to avoid inline quoting hell)
echo Creating desktop shortcut...
set "OV_PS1=%TEMP%\ov_shortcut.ps1"
set "OV_VBS=%ROOT%run.vbs"
set "OV_ICO=%ROOT%asset\image\icon.ico"
set "OV_WD=%ROOT:~0,-1%"
(
  echo $desk = [Environment]::GetFolderPath^('Desktop'^)
  echo $s = ^(New-Object -ComObject WScript.Shell^).CreateShortcut^($desk + '\Open Vending.lnk'^)
  echo $s.TargetPath = 'wscript.exe'
  echo $s.Arguments = '%OV_VBS%'
  echo $s.WorkingDirectory = '%OV_WD%'
  echo $s.IconLocation = '%OV_ICO%'
  echo $s.Save^(^)
) > "%OV_PS1%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%OV_PS1%" >> "%LOG%" 2>&1
del "%OV_PS1%"
echo [OK] Desktop shortcut created
echo [OK] Desktop shortcut created >> "%LOG%"
echo.
echo  ============================================
echo   Setup complete! Run run.bat to start.
echo  ============================================
echo.
pause
exit /b 0

:fail
echo.
echo  ============================================
echo   Setup FAILED. Check setup.log:
echo   %LOG%
echo  ============================================
echo.
pause
exit /b 1
