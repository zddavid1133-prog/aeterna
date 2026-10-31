@echo off
chcp 65001 > nul
title Aeterna Multitrack Optimizer

:: Lanza la interfaz gráfica de Aeterna Optimizer
python "%~dp0tools\optimizer.py" %*
