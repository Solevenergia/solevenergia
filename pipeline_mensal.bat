@echo off
:: ============================================================
::  CONTALEV — Pipeline Diário
::  Agendado para rodar todo dia às 22:00
:: ============================================================

set PASTA_CONTALEV=C:\Rede\CONTALEV

:: ── CONFIGURAÇÃO PRINCIPAL ───────────────────────────────────
::
::  ENVIAR_WHATSAPP=SIM  → envia cobrança via WhatsApp
::  ENVIAR_WHATSAPP=NAO  → só gera os PDFs, sem enviar
::
set ENVIAR_WHATSAPP=NAO

:: ─────────────────────────────────────────────────────────────

cd /d "%PASTA_CONTALEV%"

if not exist "%PASTA_CONTALEV%\logs" mkdir "%PASTA_CONTALEV%\logs"

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set LOGFILE=%PASTA_CONTALEV%\logs\pipeline_%DT:~0,8%.txt

echo. >> "%LOGFILE%"
echo ============================================ >> "%LOGFILE%"
echo  CONTALEV Pipeline - %DATE% %TIME% >> "%LOGFILE%"
echo  WhatsApp: %ENVIAR_WHATSAPP% >> "%LOGFILE%"
echo ============================================ >> "%LOGFILE%"

python --version >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado. >> "%LOGFILE%"
    exit /b 1
)

echo Iniciando pipeline... >> "%LOGFILE%"

if /i "%ENVIAR_WHATSAPP%"=="SIM" (
    python rodar_tudo.py --headless >> "%LOGFILE%" 2>&1
) else (
    python rodar_tudo.py --headless --sem-whatsapp >> "%LOGFILE%" 2>&1
)

if errorlevel 1 (
    echo RESULTADO: FALHOU >> "%LOGFILE%"
) else (
    echo RESULTADO: CONCLUIDO COM SUCESSO >> "%LOGFILE%"
)

echo Fim: %TIME% >> "%LOGFILE%"
exit /b 0
