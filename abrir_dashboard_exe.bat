@echo off
chcp 65001 > nul
setlocal

if exist "dist\InventarioDashboard\InventarioDashboard.exe" (
    start "" "dist\InventarioDashboard\InventarioDashboard.exe"
) else (
    echo O EXE ainda nao foi criado.
    echo Primeiro execute: criar_exe_windows.bat
    pause
)
