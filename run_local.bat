@echo off
REM ============================================================
REM  Pol Dep Federal - Instalador/Servidor LOCAL (1 clique)
REM  Requisito unico: Python 3.11+ instalado (com "Add to PATH").
REM  Banco: SQLite (arquivo dev.db criado automaticamente).
REM ============================================================
setlocal
cd /d "%~dp0"
title Pol Dep Federal - Servidor local

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERRO] Python nao encontrado nesta maquina.
  echo Instale o Python 3.11 ou superior:
  echo   https://www.python.org/downloads/
  echo IMPORTANTE: na instalacao, marque "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

if not exist .venv (
  echo Criando ambiente ^(so na primeira vez^)...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Instalando dependencias ^(pode demorar alguns minutos na 1a vez^)...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e .
if errorlevel 1 (
  echo [ERRO] Falha ao instalar dependencias. Verifique a internet e tente de novo.
  pause
  exit /b 1
)

if not exist .env (
  > .env echo DATABASE_URL=sqlite+aiosqlite:///./dev.db
  >> .env echo APP_ENV=prod
  >> .env echo CORS_ORIGINS=http://localhost:8000
)

echo.
echo ============================================================
echo   Servidor iniciando...
echo   Abra no navegador:  http://localhost:8000
echo   Para PARAR o servidor: feche esta janela.
echo ============================================================
echo.
start "" http://localhost:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
