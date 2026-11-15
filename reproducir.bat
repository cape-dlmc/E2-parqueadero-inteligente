@echo off
chcp 65001 > nul
echo ========================================================
echo   REPRODUCCION COMPLETA - PARQUEADERO INTELIGENTE (E2)
echo ========================================================
echo.

if not exist "salidas" mkdir salidas
if not exist "evidencias" mkdir evidencias

echo [1/4] Generando catálogo de zonas desde datos originales...
python -m pipeline.generar_catalogo
if %errorlevel% neq 0 goto error

echo.
echo [2/4] Carga inicial desde cero (datos_originales.csv)...
python -m pipeline.etl --reiniciar > evidencias\01_carga_inicial.json
type evidencias\01_carga_inicial.json
if %errorlevel% neq 0 goto error

echo.
echo [3/4] Segunda ejecución sobre la misma BD (comprobar que no duplica)...
python -m pipeline.etl > evidencias\02_segunda_ejecucion.json
type evidencias\02_segunda_ejecucion.json
if %errorlevel% neq 0 goto error

echo.
echo [4/4] Cargando anomalías de prueba del docente (anomalias_prueba.csv)...
python -m pipeline.etl --origen 01_dataset/anomalias_prueba.csv > evidencias\03_anomalias.json
type evidencias\03_anomalias.json
if %errorlevel% neq 0 goto error

echo.
echo [4/4] Ejecutando pruebas unitarias y de integración...
python -m pytest -q > evidencias\04_pruebas.txt
type evidencias\04_pruebas.txt
if %errorlevel% neq 0 goto error

echo.
echo ========================================================
echo  ¡TODO COMPLETADO CON ÉXITO!
echo  Resultados generados en salidas/ y evidencias/
echo ========================================================
pause
exit /b 0

:error
echo.
echo [ERROR] Ocurrió un fallo en el proceso.
pause
exit /b 1
