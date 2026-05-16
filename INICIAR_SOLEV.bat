@echo off
title SoLev Energia - Sistema de Energia Solar
color 0A

echo ============================================================
echo   SoLev Energia - Iniciando Sistema
echo ============================================================
echo.

:: Verifica se Python esta instalado
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Python nao encontrado!
    echo.
    echo Instale o Python em: https://python.org
    echo IMPORTANTE: Marque "Add Python to PATH" durante a instalacao!
    echo.
    pause
    exit /b
)

echo [OK] Python encontrado
echo.

:: Instala dependencias se necessario
echo Verificando dependencias...
pip install flask reportlab qrcode[pil] Pillow pypdfium2 pdfplumber httpx pypdf numpy >nul 2>&1
echo [OK] Dependencias instaladas
echo.

:: Inicia o servidor (le e grava direto no Supabase via db.py)
echo ============================================================
echo   Servidor iniciando...
echo   Acesse no navegador: http://localhost:5000
echo.
echo   Banco: Supabase (PostgreSQL) - leitura/escrita direta.
echo   Seu socio ve as alteracoes em tempo real (sem sync manual).
echo.
echo   Para fechar: pressione Ctrl+C ou feche esta janela.
echo ============================================================
echo.
python app.py

pause
