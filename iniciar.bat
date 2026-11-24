@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Abrir GeoCNPJ.ps1"
if errorlevel 1 (
    echo.
    echo O GeoCNPJ nao iniciou. Leia o erro acima e consulte docs\MANUAL_INSTALACAO.md.
    pause
    exit /b 1
)
