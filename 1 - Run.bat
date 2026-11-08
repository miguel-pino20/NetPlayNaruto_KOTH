@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title UN5 Netplay - proyecto local

pushd "%~dp0"
if errorlevel 1 goto folder_error

set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "UN5_SOURCE_HELPER=%~dp0windows\run_source.py"

if not exist "%UN5_SOURCE_HELPER%" goto missing_files
if not exist "%~dp0windows\requirements-run.txt" goto missing_files
if not exist "%~dp0windows\windows_start.py" goto missing_files
if not exist "%~dp0launcher.py" goto missing_files

call :probe_python "%~dp0.venv-win\Scripts\python.exe" "" "venv"
if not errorlevel 1 (
    set "UN5_PYTHON=%~dp0.venv-win\Scripts\python.exe"
    set "UN5_PYTHON_ARGS="
    goto run
)

call :probe_python "py" "-3"
if not errorlevel 1 (
    set "UN5_PYTHON=py"
    set "UN5_PYTHON_ARGS=-3"
    goto run
)

for %%V in (314 313 312 311 310) do (
    call :probe_python "%LocalAppData%\Programs\Python\Python%%V\python.exe" ""
    if not errorlevel 1 (
        set "UN5_PYTHON=%LocalAppData%\Programs\Python\Python%%V\python.exe"
        set "UN5_PYTHON_ARGS="
        goto run
    )
    call :probe_python "%ProgramFiles%\Python%%V\python.exe" ""
    if not errorlevel 1 (
        set "UN5_PYTHON=%ProgramFiles%\Python%%V\python.exe"
        set "UN5_PYTHON_ARGS="
        goto run
    )
    call :probe_python "%SystemDrive%\Python%%V\python.exe" ""
    if not errorlevel 1 (
        set "UN5_PYTHON=%SystemDrive%\Python%%V\python.exe"
        set "UN5_PYTHON_ARGS="
        goto run
    )
)

for /f "delims=" %%P in ('where python 2^>nul') do (
    call :probe_python "%%P" ""
    if not errorlevel 1 (
        set "UN5_PYTHON=%%P"
        set "UN5_PYTHON_ARGS="
        goto run
    )
)

echo.
echo No se encontro Python de Windows de 64 bits con Tcl/Tk, version 3.10 o posterior.
echo Instala Python desde https://www.python.org/downloads/windows/
echo Incluye Tcl/Tk e IDLE, pip y el launcher de Python.
echo Despues vuelve a ejecutar este archivo.
goto failure

:run
echo.
echo UN5 Netplay - usando el proyecto local, sin descargar actualizaciones de codigo.
echo No se generara ningun EXE ni se abrira PCSX2 automaticamente.
echo.
"%UN5_PYTHON%" %UN5_PYTHON_ARGS% -I "%UN5_SOURCE_HELPER%" %*
set "UN5_RESULT=%ERRORLEVEL%"
if not "%UN5_RESULT%"=="0" goto launch_error
popd
endlocal
exit /b 0

:probe_python
rem Skip the Windows Store alias; it is not an installed Python runtime.
echo "%~1" | findstr /i /c:"WindowsApps" >nul
if not errorlevel 1 exit /b 1
"%~1" %~2 -I -c "import sys, tkinter, venv, ssl; assert sys.version_info >= (3, 10) and sys.maxsize > 2**32; assert sys.argv[1] != 'venv' or sys.prefix != sys.base_prefix" "%~3" >nul 2>&1
exit /b %ERRORLEVEL%

:missing_files
echo Faltan archivos del proyecto. Actualiza el repositorio completo con Git.
goto failure

:launch_error
echo.
echo El launcher termino con un error. Revisa el mensaje anterior.
echo Si la ventana llego a abrirse, consulta tambien el registro:
echo "%APPDATA%\UN5 Netplay\launcher.log"
goto failure

:failure
pause
popd
endlocal
exit /b 1

:folder_error
echo No se pudo abrir la carpeta del proyecto.
pause
endlocal
exit /b 1
