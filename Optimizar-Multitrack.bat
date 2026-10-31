@echo off
chcp 65001 > nul
title Aeterna Multitrack Optimizer

if "%~1"=="" (
    echo.
    echo ========================================================
    echo   AETERNA MULTITRACK OPTIMIZER
    echo ========================================================
    echo.
    echo  Modo de uso:
    echo  1. Arrastra una carpeta con stems o un archivo .ZIP
    echo     directamente sobre este icono.
    echo.
    echo  O escribe la ruta de la carpeta/ZIP aqui:
    set /p input_path="> "
    if "%input_path%"=="" goto fin
    python "%~dp0tools\optimizer.py" "%input_path%"
    goto fin
)

python "%~dp0tools\optimizer.py" %*

:fin
