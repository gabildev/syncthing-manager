@echo off
:: Builds dist\windows\syncthing-manager\ (onedir folder) + the .zip
:: Run from the project root in CMD or PowerShell
::
:: Usage:  build\build_windows.bat [--no-package]
::   --no-package (aliases --no-pack / --skip-package): do NOT build the .zip, leave only the
::   onedir folder dist\windows\syncthing-manager\ -- handy for fast iteration while testing.
setlocal
set NO_PACKAGE=0
set PACKAGE_ERR=0
:parseargs
if "%~1"=="" goto endargs
if /I "%~1"=="--no-package"  set NO_PACKAGE=1
if /I "%~1"=="--no-pack"     set NO_PACKAGE=1
if /I "%~1"=="--skip-package" set NO_PACKAGE=1
shift
goto parseargs
:endargs

:: Find Python (py launcher -> python -> python3)
set PYTHON=
where py >nul 2>&1 && set PYTHON=py
if "%PYTHON%"=="" where python >nul 2>&1 && set PYTHON=python
if "%PYTHON%"=="" where python3 >nul 2>&1 && set PYTHON=python3

if "%PYTHON%"=="" (
    echo.
    echo ERROR: Python not found in PATH.
    echo.
    echo Install Python 3.10+ from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: check "Add Python to PATH" during installation.
    echo.
    echo Or install with winget:
    echo   winget install Python.Python.3.11
    echo.
    pause
    exit /b 1
)

echo Using: %PYTHON%
%PYTHON% --version

set TRUST=--trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org

echo.
echo Installing dependencies...
%PYTHON% -m pip install pyinstaller %TRUST% -q
%PYTHON% -m pip install -e . %TRUST%

rem (Re)generate the icon from its source (best-effort: needs Pillow). The specs fall back to
rem "no icon" if it fails, so a missing Pillow never breaks the build.
%PYTHON% -m pip install pillow %TRUST% -q
%PYTHON% assets\make_icon.py || echo   (note: could not generate the icon - building without one)

echo.
echo Building Windows agent (for devices without remote access)...
%PYTHON% -m PyInstaller build\agent_windows.spec --distpath dist\windows --workpath build_tmp --noconfirm
set AGENT_ERR=%ERRORLEVEL%

:: Save the freshly built Windows template into the PERSISTENT, synced store build\prebuilt\
:: so it (a) survives the final cleanup and (b) is available -via Syncthing- on the Linux
:: machine and gets embedded into its binary (cross-OS generation, #5a).
if not exist build\prebuilt mkdir build\prebuilt
if exist dist\windows\syncthing-manager-agent-template.exe copy /Y dist\windows\syncthing-manager-agent-template.exe build\prebuilt\ >nul

:: The Linux agent template (built on Linux) is picked up from build\prebuilt\ (synced by
:: Syncthing) or from dist\linux\. The spec embeds it; generating an agent only appends bytes
:: to the template, it does NOT run it, so Windows can produce Linux agents.
if exist build\prebuilt\syncthing-manager-agent-template (
    echo  + Linux agent template available ^(Linux agents can be generated^)
) else if exist dist\linux\syncthing-manager-agent-template (
    echo  + Linux agent template available ^(Linux agents can be generated^)
) else (
    echo  - Linux agent template NOT found ^(build it on Linux; build\prebuilt\
    echo    is synced by Syncthing, so rebuilding here will embed it automatically^)
)

:: The main exe embeds BOTH templates if they exist BEFORE it is built, which is why they
:: are built first.
echo.
echo Building Windows executable with embedded templates (may take 1-2 minutes)...
%PYTHON% -m PyInstaller build\windows.spec --distpath dist\windows --workpath build_tmp --noconfirm

if %ERRORLEVEL% neq 0 (
    echo.
    echo Error building the main executable. Check the messages above.
    pause
    exit /b 1
)

:: The templates are now EMBEDDED in the program folder (extracted on demand when generating
:: an agent), so we delete the loose template binaries.
del /Q dist\windows\syncthing-manager-agent-template.exe 2>nul
del /Q dist\windows\syncthing-manager-agent-template 2>nul

:: Cleanup: PyInstaller's intermediate work dir is disposable. Removing it leaves the project
:: tree clean after building.
rmdir /S /Q build_tmp 2>nul

:: onedir build (#87): the output is the FOLDER dist\windows\syncthing-manager\ (instant
:: startup, nothing to extract). We package it into a .zip for distribution.
if "%NO_PACKAGE%"=="1" (
    echo.
    echo Skipping packaging ^(--no-package^): onedir folder only.
) else (
    echo.
    echo Packaging dist\windows\syncthing-manager-windows.zip ...
    rem Bundle the licenses next to the binary (MIT + third-party attributions, incl. paramiko LGPL).
    copy /Y LICENSE dist\windows\syncthing-manager\ >nul 2>&1
    copy /Y THIRD_PARTY_LICENSES.md dist\windows\syncthing-manager\ >nul 2>&1
    del /Q dist\windows\syncthing-manager-windows.zip 2>nul
    rem Compress-Archive raises a NON-terminating error (exit 0) if the .exe is momentarily
    rem locked -- right after PyInstaller writes it, Defender/the indexer scans it and holds a
    rem read lock for a few seconds. Retry a few times (the lock is transient) and make the
    rem failure TERMINATING (exit 1) so the build can't falsely report success.
    powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $ok=$false; for($i=1;$i -le 5;$i++){ try { Compress-Archive -Path 'dist\windows\syncthing-manager' -DestinationPath 'dist\windows\syncthing-manager-windows.zip' -Force; $ok=$true; break } catch { Write-Host ('  attempt ' + $i + ' failed (file in use?), retrying in 3s...'); Start-Sleep -Seconds 3 } }; if (-not $ok) { Write-Error 'Could not create the .zip after several attempts.'; exit 1 }"
    if errorlevel 1 set PACKAGE_ERR=1
    if not exist "dist\windows\syncthing-manager-windows.zip" set PACKAGE_ERR=1
)

:: Final cleanup: remove ALL the temporary stuff PyInstaller leaves (the .spec cache in
:: build\__pycache__) and pip install -e . (*.egg-info), besides the build_tmp removed above.
:: The tree is left clean after building (only dist\ with the binaries and build\ with sources).
if exist build\__pycache__ rmdir /S /Q build\__pycache__ 2>nul
if exist build\build rmdir /S /Q build\build 2>nul
if exist build\dist rmdir /S /Q build\dist 2>nul
for /d %%d in (*.egg-info) do rmdir /S /Q "%%d" 2>nul

echo.
if "%PACKAGE_ERR%"=="1" (
    echo =============================================
    echo  ERROR: the onedir folder built, but the .zip could NOT be created
    echo    dist\windows\syncthing-manager-windows.zip
    echo  Common cause: the .exe is momentarily locked by an antivirus or the
    echo  Windows indexer ^(usually fixed by retrying^). Run this script again,
    echo  or use --no-package to keep just the onedir folder.
    echo =============================================
    if not "%AGENT_ERR%"=="0" echo  Note: the Windows agent template did not build correctly either.
    pause
    exit /b 1
)
echo =============================================
echo  Done in dist\windows\ (onedir folder):
echo    syncthing-manager\syncthing-manager.exe   (agent templates embedded)
if not "%NO_PACKAGE%"=="1" echo    syncthing-manager-windows.zip            (for distribution)
echo =============================================
if not "%AGENT_ERR%"=="0" echo  Note: the Windows agent template did not build correctly; check the messages.
pause
