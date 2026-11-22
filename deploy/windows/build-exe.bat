@echo off
rem Construieste detoate.exe - o data pentru fiecare versiune a aplicatiei, pe un
rem calculator Windows cu Python 3.9+ (poate fi chiar calculatorul casei).
rem Rezultatul: dist\detoate.exe - singurul fisier care se copiaza la casa.
rem Interfata: cu Node.js instalat se construieste aici; fara Node.js se foloseste
rem folderul frontend\dist deja construit (npm run build pe alt calculator).
setlocal
cd /d "%~dp0..\.."

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto no_python

echo.
echo [1/3] Interfata
where npm >nul 2>nul
if errorlevel 1 goto no_node
pushd frontend
call npm ci --no-audit --no-fund || (popd & goto fail)
call npm run build || (popd & goto fail)
popd
goto ui_done
:no_node
echo Node.js nu este instalat: folosesc interfata deja construita din frontend\dist.
:ui_done
if not exist frontend\dist\index.html goto no_ui

echo.
echo [2/3] Python si PyInstaller
if not exist .build-venv\Scripts\python.exe (
  %PY% -m venv .build-venv || goto fail
)
.build-venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r backend\requirements.txt pyinstaller==6.22.3 || goto fail

echo.
echo [3/3] detoate.exe
.build-venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller deploy\windows\detoate.spec || goto fail

echo.
echo Gata: %CD%\dist\detoate.exe
echo Copiati-l la casa, de exemplu in C:\detoate\ - vezi deploy\windows\README.md
pause
exit /b 0

:no_python
echo EROARE: Python nu este instalat. Instalati-l de pe https://www.python.org/downloads/
echo         si bifati "Add python.exe to PATH" la instalare, apoi rulati din nou.
goto fail

:no_ui
echo EROARE: lipseste frontend\dist\index.html. Instalati Node.js de pe https://nodejs.org
echo         sau copiati aici folderul frontend\dist construit pe alt calculator (npm run build).
goto fail

:fail
echo.
echo detoate.exe NU s-a construit - cititi mesajul de mai sus.
pause
exit /b 1
