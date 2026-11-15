@echo off
chcp 65001 > nul
echo ========================================================
echo   LEVANTANDO SERVIDOR API - PARQUEADERO INTELIGENTE
echo ========================================================
echo.
echo URL API:         http://localhost:8000
echo Swagger Docs:    http://localhost:8000/docs
echo ReDoc:           http://localhost:8000/redoc
echo.
echo Presione Ctrl+C para detener el servidor.
echo.
python -m uvicorn app.main:app --reload --port 8000
