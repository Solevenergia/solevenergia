@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ==========================================
echo   SOLEV - Gerar Cobranca
echo ==========================================
echo.

if "%~1"=="" (
    echo Arraste o PDF da Equatorial para cima deste arquivo,
    echo ou digite o nome do arquivo PDF:
    echo.
    set /p PDF="PDF: "
) else (
    set "PDF=%~1"
)

echo.
python "%~dp0gerar_cobranca_auto.py" "%PDF%"
echo.
echo.
pause
