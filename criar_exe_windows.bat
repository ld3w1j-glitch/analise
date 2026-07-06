@echo off
chcp 65001 > nul
setlocal

title Criar EXE - Dashboard de Inventario

echo ============================================================
echo   Criador de EXE - Dashboard de Inventario Rotativo
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERRO: Python nao encontrado.
    echo Instale o Python em https://www.python.org/downloads/
    echo Marque a opcao "Add Python to PATH" durante a instalacao.
    pause
    exit /b 1
)

echo [1/4] Atualizando pip...
python -m pip install --upgrade pip
if errorlevel 1 goto erro

echo.
echo [2/4] Instalando dependencias do projeto...
python -m pip install -r requirements.txt
if errorlevel 1 goto erro

echo.
echo [3/4] Instalando PyInstaller...
python -m pip install pyinstaller
if errorlevel 1 goto erro

echo.
echo [4/4] Gerando executavel...
python -m PyInstaller --clean --noconfirm InventarioDashboard.spec
if errorlevel 1 goto erro

echo.
echo ============================================================
echo EXE criado com sucesso!
echo.
echo Caminho:
echo %cd%\dist\InventarioDashboard\InventarioDashboard.exe
echo.
echo Voce pode copiar a pasta inteira:
echo %cd%\dist\InventarioDashboard
echo.
echo IMPORTANTE: mantenha os arquivos da pasta junto com o EXE.
echo ============================================================
pause
exit /b 0

:erro
echo.
echo ============================================================
echo Ocorreu um erro ao criar o EXE.
echo Tente executar este arquivo como administrador ou verifique a instalacao do Python.
echo ============================================================
pause
exit /b 1
