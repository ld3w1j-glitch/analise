@echo off
chcp 65001 > nul
title Dashboard Inventario Rotativo

echo ===============================================
echo  Dashboard Inventario Rotativo - Flask
echo ===============================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo Python nao encontrado. Instale o Python 3.10 ou superior.
    pause
    exit /b 1
)

if not exist venv (
    echo Criando ambiente virtual...
    py -m venv venv
)

call venv\Scripts\activate

echo Instalando dependencias...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Iniciando o dashboard...
echo Abra no navegador: http://127.0.0.1:5000
echo.
python app.py
pause
