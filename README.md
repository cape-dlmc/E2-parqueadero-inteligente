# Parqueadero inteligente universitario · E2 · Aplicación conectada y datos preparados

Sistema que **recibe** lecturas de ocupación de zonas de parqueo, las **valida**, las **guarda** en una base de datos SQLite, las **consulta** por API y **prepara** los datos desde su fuente original con un pipeline reproducible.

Continuidad: el modelo, las restricciones y las reglas vienen de E1 (`02_notebook/`, `03_informe/`).

---

## 1. Requisitos

- Python 3.10 o superior
- Conexión a internet solo para instalar las dependencias (la ejecución es local)

## 2. Reproducir todo desde cero (un solo comando)

Desde la carpeta raíz del proyecto:

```bash
pip install -r requirements.txt
bash reproducir.sh
```

Si estás en Windows y no tienes `bash`, ejecuta los mismos cuatro pasos a mano (sección 3).

`reproducir.sh` hace, en orden:

1. Genera `01_dataset/catalogo_zonas.csv` a partir de `01_dataset/datos_originales.csv`.
2. Borra la base y la reconstruye desde los datos originales (`--reiniciar`).
3. Vuelve a ejecutar el pipeline sobre la misma base para comprobar que **no duplica**.
4. Carga el archivo de anomalías del docente (`01_dataset/anomalias_prueba.csv`).
5. Corre las 23 pruebas automáticas.

Al terminar, los resultados quedan en `salidas/` (base de datos, rechazados, reconciliación, producto final) y en `evidencias/` (registro de cada ejecución).

**Resultado esperado** (lo que debe verse si todo sale bien):

| Ejecución | Filas leídas | Nuevas | Ya existían | Duplicados descartados | Rechazadas | Cuadra |
|---|---|---|---|---|---|---|
| 1. Carga inicial | 35.717 | 35.116 | 0 | 216 | 385 | sí |
| 2. Segunda ejecución | 35.717 | 0 | 35.116 | 216 | 385 | sí |
| 3. Anomalías del docente | 15 | 2 | 1 | 1 | 11 | sí |

Pruebas: `23 passed`.

## 3. Pasos manuales (equivalentes a `reproducir.sh`)

```bash
python -m pipeline.generar_catalogo
python -m pipeline.etl --reiniciar
python -m pipeline.etl                                   # segunda ejecución: no duplica
python -m pipeline.etl --origen 01_dataset/anomalias_prueba.csv
python -m pytest -q
```

El código de salida del pipeline es `0` si la reconciliación y la consistencia de la base cuadran, y `1` si no.

## 4. Levantar la API

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Documentación interactiva (Swagger): `http://localhost:8000/docs`

Para usar otra base de datos, sin tocar la entregable:

```bash
PARQUEADERO_DB=/ruta/copia.db python -m uvicorn app.main:app --port 8000
```

### Endpoints

| Método | Ruta | Qué hace | Respuestas |
|---|---|---|---|
| GET | `/health` | Verifica que la API responde | 200 |
| GET | `/zonas` | Lista zonas y capacidad | 200 |
| POST | `/lecturas` | Recibe una lectura, la valida y la guarda | 201 creada · 200 ya existía · 409 conflicto · 404 zona inexistente · 422 validación |
| GET | `/zonas/{codigo}/ultima` | Última ocupación de una zona, con porcentaje y cupos libres | 200 · 404 |
| GET | `/zonas/recomendadas?limite=5` | Zonas con más cupos libres (menor porcentaje primero) | 200 · 422 |

### Ejemplo de entrada y salida

```bash
curl -X POST localhost:8000/lecturas -H "Content-Type: application/json" \
  -d '{"codigo_zona":"BHMBCCMKT01","fecha_hora":"2016-12-22 12:00:00","ocupacion":210}'
```

```json
{"estado":"creada","lectura":{"codigo_zona":"BHMBCCMKT01","fecha_hora":"2016-12-22 12:00:00","ocupacion":210}}
```

### Errores distinguibles

Todo error responde con el mismo formato, y el campo `codigo` es estable y se puede usar en código:

```json
{"error":{"codigo":"OCUPACION_SUPERA_CAPACIDAD","mensaje":"ocupacion 900 supera la capacidad 577 de la zona","campo":"ocupacion"}}
```

| Código | Cuándo ocurre | HTTP |
|---|---|---|
| `CAMPO_INCOMPLETO` | Falta un campo o viene vacío | 422 |
| `CAMPO_INVALIDO` | La ocupación no es un entero (`abc`, `12.5`) | 422 |
| `FECHA_INVALIDA` | La fecha no tiene formato `AAAA-MM-DD HH:MM:SS` | 422 |
| `OCUPACION_NEGATIVA` | Ocupación menor que 0 | 422 |
| `OCUPACION_SUPERA_CAPACIDAD` | Ocupación mayor que la capacidad de la zona | 422 |
| `JSON_INVALIDO` | El cuerpo no es JSON válido o faltan parámetros | 422 |
| `ZONA_INEXISTENTE` | La zona no está en el catálogo | 404 |
| `SIN_LECTURAS` | La zona existe pero aún no tiene lecturas | 404 |
| `LECTURA_CONFLICTIVA` | Ya hay una lectura de esa zona a esa hora con **otro** valor | 409 |

Si llega la **misma** lectura otra vez, la API no duplica: responde `200` con `"estado":"ya_existia"`.

## 5. Estructura del proyecto

```
app/                  API y reglas
  reglas.py           validaciones y códigos de error (la misma regla en la API y en el pipeline)
  servicio.py         lógica: registrar y consultar lecturas
  main.py             endpoints FastAPI
  db.py               conexión y esquema SQLite
pipeline/
  generar_catalogo.py crea el catálogo de zonas desde los datos originales
  etl.py              pipeline reproducible (validar → resolver duplicados → cargar → reconciliar)
schema.sql            esquema de la base (idéntico al de E1, con índice)
tests/                23 pruebas: reglas, API y pipeline
01_dataset/
  datos_originales.csv     fuente original (35.717 filas)
  catalogo_zonas.csv       30 zonas con su capacidad (se genera con pipeline/generar_catalogo.py)
  anomalias_prueba.csv     15 filas con defectos a propósito (anomalía del docente)
salidas/              resultados del pipeline (base, rechazados, reconciliación, producto final)
evidencias/           registro de cada ejecución (JSON, pruebas, recorrido de la API)
docs/                 predicción, decisiones de arquitectura, bitácora, recorrido E2E (PDF)
02_notebook/, 03_informe/   material de E1 (sin cambios)
```

## 6. Reglas de limpieza y de validación

El pipeline procesa cada fila en este orden, y se detiene en la primera regla que falla:

1. **Campos completos**: `SystemCodeNumber`, `LastUpdated` y `Occupancy` no vacíos.
2. **Fecha con formato** `AAAA-MM-DD HH:MM:SS`.
3. **Ocupación entera** (sin decimales ni texto).
4. **Ocupación no negativa.**
5. **Zona existente** en el catálogo.
6. **Ocupación ≤ capacidad** de la zona (capacidad del catálogo, no la que reporta el sensor).

Después de validar cada fila:

- **Duplicado exacto dentro del archivo** (misma zona, misma hora, mismo valor): se conserva una y se cuenta como descartado. No es un error.
- **Conflicto dentro del archivo** (misma zona y hora, valores distintos): se rechazan **todas** las filas de ese grupo. No se adivina cuál es la correcta.
- **Ya existe en la base con el mismo valor**: se cuenta como "ya existía" y no se vuelve a insertar.
- **Ya existe en la base con otro valor**: se rechaza como `LECTURA_CONFLICTIVA`.
- **Capacidad reportada distinta del catálogo**: no rechaza; se cuenta como advertencia en la reconciliación.

Cada rechazo queda en `salidas/rechazados_<archivo>.csv` con su número de línea y su motivo. La columna `linea_origen` cuenta el encabezado (la primera lectura es la línea 2).

## 7. Reconciliación

Para cada corrida, `salidas/reconciliacion_<archivo>.json` debe cumplir:

```
filas_leidas = aceptadas_nuevas + ya_existian_identicas + duplicados_exactos_descartados + rechazadas
```

y además:

```
lecturas_en_bd_antes + aceptadas_nuevas = lecturas_en_bd_despues
```

Si alguna de las dos no se cumple, el pipeline termina con código `1`.

## 8. Transacciones

Toda la carga corre dentro de **una sola transacción** (`BEGIN` … `COMMIT`). Si ocurre un error a mitad de camino, se hace `ROLLBACK` y la base queda como estaba antes de la corrida. Por eso no existen cargas a medias.

## 9. Pruebas

```bash
python -m pytest -q
```

- `tests/test_reglas.py`: cada regla devuelve su código de error.
- `tests/test_api.py`: cada respuesta de la API (201, 200, 404, 409, 422) y los errores de formato.
- `tests/test_pipeline.py`: reconciliación cuadra y una segunda ejecución no duplica.

## 10. Limitaciones conocidas

- **Dataset de origen**: es un dataset de parqueaderos de Birmingham (2016). Cada `SystemCodeNumber` se trata como una zona del campus. Esto está explicado en el informe de E1.
- **SQLite es local**: sirve para un solo equipo. Para varios usuarios simultáneos haría falta un motor servidor (ver `docs/decision_arquitectura.md`).
- **La API no tiene autenticación**: en esta etapa solo corre en la máquina local.
- **Sin datos en tiempo real**: el sensor no existe; las lecturas se envían por API o por archivo.
