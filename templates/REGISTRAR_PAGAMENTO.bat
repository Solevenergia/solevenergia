@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ==========================================
echo   SOLEV - Registrar Pagamento
echo ==========================================
echo.
echo Clientes cadastrados:
echo.
python "%~dp0gerar_cobranca_auto.py" --listar
echo.
echo.
set /p UC="Unidade Consumidora (UC): "
set /p DATA="Data do pagamento (dd/mm/aaaa): "
echo.
python "%~dp0gerar_cobranca_auto.py" --pagar %UC% %DATA%
echo.
pause
