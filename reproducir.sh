#!/usr/bin/env bash
# Reproduce TODO el proyecto desde los datos originales.
# Uso:  bash reproducir.sh      (desde la carpeta raíz del proyecto)
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p salidas evidencias

echo "[1/4] Catálogo de zonas desde datos originales"
python -m pipeline.generar_catalogo

echo "[2/4] Carga inicial desde cero (datos_originales.csv)"
python -m pipeline.etl --reiniciar | tee evidencias/01_carga_inicial.json

echo "[3/4] Segunda ejecución sobre la misma BD (no debe duplicar)"
python -m pipeline.etl | tee evidencias/02_segunda_ejecucion.json

echo "[4/4] Anomalías del docente (anomalias_prueba.csv)"
python -m pipeline.etl --origen 01_dataset/anomalias_prueba.csv | tee evidencias/03_anomalias.json

echo "Pruebas automáticas"
python -m pytest -q | tee evidencias/04_pruebas.txt
echo "Listo. Resultados en salidas/ y evidencias/."
