@echo off
:: ABOUT
:: Windows CI build file for Artisan
::

set ARTISAN_SPEC=win

:: prefer the repo venv toolchain when present (local builds) so python/pyinstaller/
:: create-version-file all resolve to the same interpreter; no-op on CI (no .venv there)
if exist "%~dp0..\.venv\Scripts\python.exe" set "PATH=%~dp0..\.venv\Scripts;%PATH%"

python -V

::
:: build derived files
::
echo ""************* build derived files **************"

::call build-tilauscope-derived-win.bat
::if ERRORLEVEL 1 (echo ** Failed in build-derived-win.bat & exit /b 1) else (echo ** Finished build-dependant-win.bat)

::
:: run pyinstaller and NSIS to generate the install .exe
::
:: set environment variables for version and build
for /f "usebackq delims==" %%a IN (`python -c "import artisanlib; print(artisanlib.__version__)"`) DO (set TILAUSCOPE_VERSION=%%~a)
for /f "usebackq delims==" %%a IN (`python -c "import artisanlib; print(artisanlib.__build__)"`) DO (set TILAUSCOPE_BUILD=%%~a)
::
:: create a version file for pyinstaller
create-version-file version-metadata.yml --outfile version_info-win.txt --version %TILAUSCOPE_VERSION%.%TILAUSCOPE_BUILD%

::
:: run pyinstaller
:: Choose log-level from 'TRACE', 'DEBUG', 'INFO', 'WARN', 'DEPRECATION', 'ERROR', 'FATAL'
SET "CURRENT_DIR=%~dp0"
for %%I in ("%~dp0..") do SET "PARENT_DIR=%%~fI"
echo ** current %CURRENT_DIR%
echo ** parent %PARENT_DIR%
echo **** Running pyinstaller
pyinstaller --noconfirm --log-level=WARN setup-tilauscope-win.spec
if ERRORLEVEL 1 (echo ** Failed in pyinstaller & exit /b 1) else (echo ** Success)

::
:: Don't make assumptions as to where the 'makensis.exe' is - look in the obvious places
if exist "/Program Files (x86)/NSIS/makensis.exe"   set NSIS_EXE="/Program Files (x86)/NSIS/makensis.exe"
if exist "/Program Files/NSIS/makensbuild-wis.exe"  set NSIS_EXE="/Program Files/NSIS/makensis.exe"
if exist "%ProgramFiles%/NSIS/makensis.exe"         set NSIS_EXE="%ProgramFiles%/NSIS/makensis.exe"
if exist "%ProgramFiles(x86)%/NSIS/makensis.exe"    set NSIS_EXE="%ProgramFiles(x86)%/NSIS/makensis.exe"

::
:: run NSIS to build the install .exe file
%NSIS_EXE% /DPRODUCT_VERSION=%TILAUSCOPE_VERSION% /V4 /P2 /DPRODUCT_BUILD=%TILAUSCOPE_BUILD% setup-tilauscope.nsi
if ERRORLEVEL 1 (echo ** Failed in NSIS & exit /b 1) else (echo ** Success)

echo *** uploading 
python ..\scripts\main.py
