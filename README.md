# Parqueadero inteligente universitario · sede Montería

Aplicación web y API para consultar y reservar cupos en las 30 zonas de parqueo de una sede universitaria.

Permite ver la ocupación de cada zona en vivo, conocer las restricciones de reserva (vehículos permitidos, horario, duración máxima), reservar un cupo, consultar y cancelar reservas, y recibir una alerta o una predicción sencilla con los datos de la propia base.

## Qué hace

- **Recibe y valida lecturas** de ocupación de sensores o de archivos. Las reglas de validación viven en un solo lugar (`app/reglas.py`) y las usan la API y el pipeline.
- **Guarda en SQLite** con claves foráneas, restricciones `CHECK` e índices. Las restricciones por zona están en la tabla `restriccion_zona`; las reservas, en `reserva`.
- **Reserva con bloqueo**: la creación de una reserva ocurre dentro de una transacción `BEGIN IMMEDIATE`, así dos personas no toman el mismo cupo.
- **Protege formularios y contraseñas**: la API rechaza texto con etiquetas HTML o código (`TEXTO_PELIGROSO`), la interfaz escapa todo lo que muestra, las consultas usan parámetros y las claves se guardan con PBKDF2-SHA256 y sal.
- **Alerta e inteligencia**: una regla fija clasifica cada zona como `normal`, `atencion` o `critica`; un promedio histórico por día de la semana y hora estima la ocupación de una zona para una fecha dada.
- **Pipeline reproducible** (`pipeline/etl.py`): carga los datos originales, descarta duplicados idénticos, rechaza contradicciones y no duplica al repetir la carga.

## Estructura

```
app/
  main.py          API (FastAPI): rutas, documentación y la interfaz web
  servicio.py      lógica de zonas, lecturas, reservas y claves
  reglas.py        reglas de validación y códigos de error estables
  db.py            conexión y esquema de SQLite (con migración de columnas)
  seguridad.py     hash de contraseñas y validación de texto
  inteligencia.py  alerta por regla y predicción por promedio histórico
  static/          interfaz web (HTML, CSS, JavaScript)
pipeline/
  etl.py           carga reproducible desde 01_dataset/
  generar_catalogo.py  genera el catálogo de zonas a partir de los datos originales
01_dataset/        datos de origen y catálogos (CSV)
tests/             pruebas automáticas (pytest)
schema.sql         esquema de la base de datos
demostracion_momento3.py  recorre el flujo completo y muestra cada respuesta
reproducir.sh / reproducir.bat  reconstruyen la base desde cero
iniciar_api.bat    arranca el servidor en Windows
```

## Requisitos

- Python 3.10 o superior.
- Internet solo para instalar las dependencias. La aplicación corre en local.

## Instalación y ejecución

Desde la carpeta raíz del proyecto:

```bash
pip install -r requirements.txt
```

**Reconstruir la base desde los datos originales** (recomendado la primera vez):

```bash
python -m pipeline.etl --reiniciar
```

En Linux o macOS puedes usar `bash reproducir.sh`, que hace todo el pipeline en orden. En Windows, usa `reproducir.bat`.

**Levantar la aplicación:**

```bash
python -m uvicorn app.main:app --reload
```

Luego abre:

- Interfaz web: http://127.0.0.1:8000/
- Documentación interactiva de la API: http://127.0.0.1:8000/docs

## Pruebas

```bash
python -m pytest -q
```

Debe terminar con todas las pruebas en verde (62 en esta versión). Las pruebas usan una base temporal y no modifican la base del proyecto.

Demostración del flujo completo, paso a paso:

```bash
python demostracion_momento3.py
```

## Endpoints principales

| Método | Ruta | Para qué sirve |
|---|---|---|
| GET | `/zonas` | Zonas con ubicación, restricciones y cupos disponibles |
| GET | `/zonas/{codigo}/restricciones` | Restricciones de una zona |
| GET | `/zonas/{codigo}/disponibilidad` | Cupos libres en un intervalo |
| GET | `/zonas/{codigo}/ultima` | Última ocupación registrada |
| GET | `/zonas/{codigo}/alerta` | Alerta por regla: normal, atención o crítica |
| GET | `/zonas/{codigo}/prediccion` | Ocupación estimada para un día y hora |
| POST | `/reservas` | Crear una reserva (validada contra las restricciones) |
| GET | `/reservas?identificacion=` | Reservas de una persona |
| POST | `/reservas/{id}/cancelar` | Cancelar una reserva |
| POST | `/reservas/{id}/ampliar` | Ampliar el tiempo de una reserva activa |
| POST | `/usuarios/{id}/clave` | Guardar la clave de una persona (con hash) |
| POST | `/usuarios/{id}/verificar-clave` | Verificar la clave de una persona |
| POST | `/lecturas` | Registrar una lectura de ocupación (idempotente) |

Todo error responde con el formato `{"error": {"codigo", "mensaje", "campo"}}`. Los códigos están documentados en `/docs`.

## Decisiones de diseño

- **Una sola fuente de reglas.** La API y el pipeline validan con `app/reglas.py`, así un dato rechazado en uno se rechaza también en el otro.
- **Validación en el servidor.** El navegador ayuda con mensajes claros, pero no es la barrera de seguridad: cualquiera puede llamar la API directamente.
- **Regla fija para la alerta, promedio para la predicción.** El criterio de la alerta es explicable y no necesita entrenar nada. La predicción usa las lecturas propias de la base; no considera clima ni festivos.
- **SQLite para un solo equipo.** Simplifica la entrega. Para varios usuarios escribiendo a la vez, la base debe pasar a un motor cliente-servidor.

## Limitaciones conocidas

- La autenticación es por clave de persona; no hay inicio de sesión de usuarios.
- SQLite admite un escritor a la vez.
- Los umbrales de la alerta (90 % y 70 %) se fijaron con criterio propio y deben calibrarse con datos reales del campus.
- Las coordenadas de la sede son aproximadas.
