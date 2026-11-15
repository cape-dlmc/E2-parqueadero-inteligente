"""API de E2: recibe, valida, guarda y consulta lecturas de ocupación.

Cada error devuelve un código estable, por ejemplo:
{"error": {"codigo": "OCUPACION_SUPERA_CAPACIDAD", "mensaje": "...", "campo": "ocupacion"}}
"""
import json
import pathlib
import re
import subprocess
import sys
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional

from fastapi import FastAPI, Path, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app import db, inteligencia, reglas, servicio

RAIZ = pathlib.Path(__file__).resolve().parent.parent
STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
INDEX_HTML_PATH = STATIC_DIR / "index.html"


# ==========================================================================
# Documentación de la API (Swagger en /docs y ReDoc en /redoc)
# ==========================================================================
DESCRIPCION_API = """
Sistema para registrar y consultar la **ocupación de zonas de un parqueadero universitario**.

Recibe lecturas de sensores, las **valida** con seis reglas, las **guarda** en SQLite de forma
transaccional y permite consultar la última ocupación de cada zona y las zonas con más cupos libres.

### Flujo típico
1. Consulta `GET /zonas` para conocer los códigos y la capacidad de cada zona.
2. Envía lecturas con `POST /lecturas`.
3. Consulta el estado con `GET /zonas/{codigo}/ultima` o `GET /zonas/recomendadas`.

### Idempotencia
Enviar la **misma** lectura dos veces no duplica datos: la segunda vez responde `200` con
`"estado": "ya_existia"`. Enviar otro valor para la misma zona y hora responde `409`.

### Códigos de error
Todo error tiene el mismo formato `{"error": {"codigo", "mensaje", "campo"}}`.
El campo `codigo` es estable y puede usarse en programas.

| Código | Cuándo ocurre | HTTP |
|---|---|---|
| `CAMPO_INCOMPLETO` | Falta un campo o viene vacío | 422 |
| `CAMPO_INVALIDO` | La ocupación no es un entero | 422 |
| `FECHA_INVALIDA` | La fecha no tiene formato `AAAA-MM-DD HH:MM:SS` | 422 |
| `OCUPACION_NEGATIVA` | Ocupación menor que 0 | 422 |
| `OCUPACION_SUPERA_CAPACIDAD` | Ocupación mayor que la capacidad de la zona | 422 |
| `JSON_INVALIDO` | El cuerpo no es JSON válido o faltan parámetros | 422 |
| `ZONA_INEXISTENTE` | La zona no está en el catálogo | 404 |
| `SIN_LECTURAS` | La zona existe pero aún no tiene lecturas | 404 |
| `LECTURA_CONFLICTIVA` | Ya hay una lectura de esa zona a esa hora con otro valor | 409 |
| `RANGO_INVALIDO` | La hora de fin no es posterior a la de inicio | 422 |
| `RESERVA_EN_PASADO` | La reserva empieza antes de la hora actual de Montería | 422 |
| `ZONA_NO_RESERVABLE` | La zona existe pero no admite reservas | 422 |
| `TIPO_NO_PERMITIDO` | El vehículo (carro o moto) no está permitido en esa zona | 422 |
| `FUERA_DE_HORARIO` | La reserva cae fuera del horario de la zona o cruza dos días | 422 |
| `DURACION_EXCEDIDA` | La reserva supera el máximo de horas de la zona | 422 |
| `LIMITE_RESERVAS_USUARIO` | La persona ya tiene el máximo de reservas activas | 409 |
| `USUARIO_CON_RESERVA_SOLAPADA` | La persona ya tiene otra reserva en ese horario | 409 |
| `SIN_CUPOS_RESERVA` | La zona no tiene cupos libres en ese horario | 409 |
| `RESERVA_NO_ENCONTRADA` | No existe la reserva indicada | 404 |
| `RESERVA_YA_CANCELADA` | La reserva ya estaba cancelada | 409 |
| `RESERVA_VENCIDA` | La reserva ya terminó y no se puede cancelar | 409 |

### Reservas
Cada zona tiene **restricciones**: si admite reservas, qué vehículos entran, su horario, la duración máxima
y cuántas reservas activas puede tener una persona. Las reservas se guardan en la base de datos.
Las reservas se validan en orden y se crean dentro de una transacción con bloqueo, así dos personas no pueden tomar el mismo cupo.
"""

TAGS = [
    {"name": "Zonas", "description": "Catálogo de zonas y su ocupación actual."},
    {"name": "Lecturas", "description": "Registro de lecturas de ocupación enviadas por sensores o por archivo."},
    {"name": "Reservas", "description": "Reservar, consultar y cancelar cupos en las zonas de la sede Montería."},
    {"name": "Sistema", "description": "Estado de la API."},
]

REDOC_TEMA = {
    "colors": {"primary": {"main": "#06b6d4"}},
    "sidebar": {"backgroundColor": "#0c111d", "textColor": "#e2e8f0"},
    "rightPanel": {"backgroundColor": "#070a12"},
    "typography": {
        "fontFamily": "Inter, system-ui, Segoe UI, sans-serif",
        "headings": {"fontFamily": "Inter, system-ui, Segoe UI, sans-serif"},
        "code": {"fontFamily": "Consolas, Menlo, monospace", "backgroundColor": "#111827"},
    },
    "hideDownloadButton": False,
    "expandResponses": "200,201",
    "pathInMiddlePanel": True,
}


class Salud(BaseModel):
    estado: str = Field(description="`ok` cuando la API responde.", examples=["ok"])


class Sede(BaseModel):
    id: int = Field(examples=[1])
    nombre: str = Field(examples=["Sede Montería · Campus principal"])
    ciudad: str = Field(examples=["Montería"])
    departamento: str = Field(examples=["Córdoba"])
    latitud: float = Field(description="Latitud aproximada de la sede.", examples=[8.7479])
    longitud: float = Field(description="Longitud aproximada de la sede.", examples=[-75.8814])


class ZonaDetalle(BaseModel):
    codigo_zona: str = Field(description="Código único de la zona.", examples=["BHMBCCMKT01"])
    capacidad: int = Field(description="Número máximo de vehículos que caben en la zona.", examples=[577])
    nombre: str = Field(description="Nombre para mostrar en la sede.", examples=["Norte · Bloque 1"])
    sector: str = Field(description="Sector de la sede donde está la zona.", examples=["Norte"])
    x: int = Field(description="Posición horizontal en el esquema de la sede (0 a 100).", examples=[8])
    y: int = Field(description="Posición vertical en el esquema de la sede (0 a 100).", examples=[10])
    reservable: bool = Field(description="`false` si la zona no admite reservas.")
    tipos_permitidos: list[str] = Field(description="Vehículos que pueden reservar en la zona.", examples=[["carro", "moto"]])
    hora_apertura: str = Field(description="Primera hora con reservas (HH:MM).", examples=["06:00"])
    hora_cierre: str = Field(description="Última hora con reservas (HH:MM).", examples=["22:00"])
    horario: str = Field(description="Horario en texto.", examples=["06:00 – 22:00"])
    max_horas_reserva: int = Field(description="Duración máxima de una reserva, en horas.", examples=[8])
    max_reservas_activas_usuario: int = Field(description="Reservas activas que puede tener una persona en la zona.", examples=[2])
    nota: str = Field(default="", description="Aclaración sobre la zona, si aplica.")
    reservas_activas: int = Field(default=0, description="Cantidad de reservas activas en este momento en la zona.")
    cupos_disponibles: Optional[int] = Field(default=None, description="Cupos libres calculados restando reservas activas.")


class AmpliarReservaEntrada(BaseModel):
    minutos: int = Field(default=30, ge=5, le=480, description="Minutos a ampliar a la reserva.", examples=[30])


class DisponibilidadZona(BaseModel):
    codigo_zona: str
    inicio: str = Field(examples=["2036-06-10 08:00:00"])
    fin: str = Field(examples=["2036-06-10 12:00:00"])
    capacidad: int
    reservas_que_se_cruzan: int = Field(description="Reservas activas que se solapan con el intervalo.")
    cupos_para_reservar: int = Field(description="Capacidad menos las reservas que se solapan.")
    reservable: bool


class ReservaEntrada(BaseModel):
    """Cuerpo para crear una reserva. Los campos llegan sin tipo fijo para que las reglas
    devuelvan códigos de error propios."""
    identificacion: Optional[Any] = Field(default=None, description="Identificación de la persona. Con ella se cuentan sus reservas.", examples=["1001234567"])
    nombre: Optional[Any] = Field(default=None, description="Nombre de la persona.", examples=["Ana Pérez"])
    tipo_vehiculo: Optional[Any] = Field(default=None, description="`carro` o `moto`.", examples=["carro"])
    placa: Optional[Any] = Field(default=None, description="Opcional. Se guarda en mayúsculas.", examples=["ABC123"])
    codigo_zona: Optional[Any] = Field(default=None, description="Código de una zona de la sede.", examples=["BHMBCCMKT01"])
    inicio: Optional[Any] = Field(default=None, description="Inicio, `AAAA-MM-DD HH:MM:SS`, hora de Montería.", examples=["2036-06-10 08:00:00"])
    fin: Optional[Any] = Field(default=None, description="Fin, `AAAA-MM-DD HH:MM:SS`, mismo día que el inicio.", examples=["2036-06-10 12:00:00"])

    model_config = ConfigDict(json_schema_extra={
        "examples": [{"identificacion": "1001234567", "nombre": "Ana Pérez", "tipo_vehiculo": "carro",
                      "placa": "ABC123", "codigo_zona": "BHMBCCMKT01",
                      "inicio": "2036-06-10 08:00:00", "fin": "2036-06-10 12:00:00"}]
    })


class ReservaDetalle(BaseModel):
    id: int = Field(examples=[1])
    codigo_zona: str = Field(examples=["BHMBCCMKT01"])
    zona_nombre: str = Field(examples=["Norte · Bloque 1"])
    identificacion: str = Field(examples=["1001234567"])
    nombre: str = Field(examples=["Ana Pérez"])
    tipo_vehiculo: str = Field(examples=["carro"])
    inicio: str = Field(examples=["2036-06-10 08:00:00"])
    fin: str = Field(examples=["2036-06-10 12:00:00"])
    estado: Literal["activa", "cancelada"]
    creada_en: str = Field(description="Momento en que se creó la reserva (hora de Montería).")


class LecturaEntrada(BaseModel):
    """Cuerpo de una lectura. Los campos llegan sin tipo fijo para que las reglas
    devuelvan códigos de error propios en lugar de un error genérico de formato."""
    codigo_zona: Optional[Any] = Field(
        default=None, description="Código de una zona existente en el catálogo.",
        examples=["BHMBCCMKT01"])
    fecha_hora: Optional[Any] = Field(
        default=None, description="Fecha y hora de la lectura con formato `AAAA-MM-DD HH:MM:SS`.",
        examples=["2016-12-22 12:00:00"])
    ocupacion: Optional[Any] = Field(
        default=None, description="Número de vehículos en la zona en ese momento. Entero, entre 0 y la capacidad.",
        examples=[210])

    model_config = ConfigDict(json_schema_extra={
        "examples": [{"codigo_zona": "BHMBCCMKT01", "fecha_hora": "2016-12-22 12:00:00", "ocupacion": 210}]
    })


class LecturaRegistrada(BaseModel):
    codigo_zona: str
    fecha_hora: str = Field(examples=["2016-12-22 12:00:00"])
    ocupacion: int = Field(examples=[210])


class RespuestaLectura(BaseModel):
    estado: Literal["creada", "ya_existia"] = Field(
        description="`creada` si se guardó (201). `ya_existia` si ya estaba idéntica en la base (200).")
    lectura: LecturaRegistrada


class ErrorDetalle(BaseModel):
    codigo: str = Field(description="Código estable del error. Ver la tabla de la descripción de la API.",
                        examples=["OCUPACION_SUPERA_CAPACIDAD"])
    mensaje: str = Field(description="Explicación legible para una persona.",
                         examples=["ocupacion 900 supera la capacidad 577 de la zona"])
    campo: Optional[str] = Field(default=None, description="Campo que causó el error, si aplica.",
                                 examples=["ocupacion"])


class ErrorRespuesta(BaseModel):
    error: ErrorDetalle


class UltimaOcupacion(BaseModel):
    codigo_zona: str = Field(examples=["BHMBCCMKT01"])
    capacidad: int = Field(examples=[577])
    fecha_hora: str = Field(description="Momento de la última lectura.", examples=["2016-12-22 12:00:00"])
    ocupacion: int = Field(examples=[210])
    porcentaje_ocupado: float = Field(description="Porcentaje de la capacidad ocupado.", examples=[36.4])
    cupos_libres: int = Field(description="Capacidad menos ocupación.", examples=[367])


class ZonaRecomendada(UltimaOcupacion):
    """Igual que la última ocupación. Se incluye en la lista ordenada de recomendadas."""


# ==========================================================================
# Aplicación
# ==========================================================================
@asynccontextmanager
async def lifespan(_app):
    db.asegurar_esquema()
    yield


app = FastAPI(
    title="Parqueadero inteligente universitario",
    version="2.0.0",
    summary="Registro, validación y consulta de ocupación de zonas de parqueo.",
    description=DESCRIPCION_API,
    openapi_tags=TAGS,
    docs_url=None,
    redoc_url=None,
    contact={"name": "Entrega E2 · Computación en la Nube / Parqueadero inteligente"},
    lifespan=lifespan,
)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _error(codigo, mensaje, campo=None):
    return JSONResponse(
        status_code=reglas.HTTP_POR_CODIGO.get(codigo, 422),
        content={"error": {"codigo": codigo, "mensaje": mensaje, "campo": campo}},
    )


@app.exception_handler(reglas.ErrorValidacion)
async def _error_negocio(_request, exc):
    return _error(exc.codigo, exc.mensaje, exc.campo)


@app.exception_handler(RequestValidationError)
async def _error_formato(_request, _exc):
    return _error(reglas.JSON_INVALIDO, "El cuerpo o los parámetros no tienen el formato esperado")


RESPUESTAS_ERROR_LECTURA = {
    404: {"model": ErrorRespuesta, "description": "`ZONA_INEXISTENTE`: el código no está en el catálogo."},
    409: {"model": ErrorRespuesta, "description": "`LECTURA_CONFLICTIVA`: misma zona y hora con otro valor."},
    422: {"model": ErrorRespuesta, "description": "Validación: `CAMPO_INCOMPLETO`, `CAMPO_INVALIDO`, `FECHA_INVALIDA`, `OCUPACION_NEGATIVA`, `OCUPACION_SUPERA_CAPACIDAD` o `JSON_INVALIDO`."},
}


# ----- Sistema --------------------------------------------------------------
@app.get("/health", tags=["Sistema"], response_model=Salud, summary="Verificar que la API responde",
         description="Sirve para comprobar que el servidor está arriba antes de enviar lecturas.")
def salud():
    return {"estado": "ok"}


# ----- Zonas ----------------------------------------------------------------
@app.get("/sedes", tags=["Zonas"], response_model=list[Sede], summary="Sedes del sistema",
         description="Sede única del proyecto: el campus de Montería, con su ubicación aproximada.")
def sedes():
    con = db.conectar()
    try:
        return servicio.listar_sedes(con)
    finally:
        con.close()


@app.get("/zonas", tags=["Zonas"], response_model=list[ZonaDetalle], summary="Zonas con ubicación y restricciones",
         description="Las 30 zonas de la sede Montería, con su sector, posición en el esquema, capacidad "
                     "y las restricciones que aplican a las reservas.")
def zonas():
    con = db.conectar()
    try:
        return servicio.listar_zonas(con)
    finally:
        con.close()


@app.get("/zonas/{codigo}/restricciones", tags=["Zonas"], response_model=ZonaDetalle,
         summary="Restricciones de una zona",
         description="Devuelve la zona con sus restricciones de reserva: si es reservable, vehículos permitidos, "
                     "horario, duración máxima y reservas activas por persona.",
         responses={404: {"model": ErrorRespuesta, "description": "`ZONA_INEXISTENTE`."}})
def zona_restricciones(codigo: str = Path(description="Código de la zona.", examples=["BHMBCCMKT01"])):
    con = db.conectar()
    try:
        return servicio.detalle_zona(con, codigo)
    finally:
        con.close()


@app.get("/zonas/recomendadas", tags=["Zonas"], response_model=list[ZonaRecomendada],
         summary="Zonas con más cupos libres",
         description="Ordena las zonas de menor a mayor porcentaje ocupado, usando la última lectura de cada una. "
                     "Útil para indicar dónde parquear.",
         responses={422: {"model": ErrorRespuesta, "description": "`limite` fuera de rango (1 a 30)."}})
def zonas_recomendadas(limite: int = Query(5, ge=1, le=30,
                                           description="Cantidad de zonas a devolver (1 a 30).",
                                           examples=[3])):
    con = db.conectar()
    try:
        return servicio.recomendadas(con, limite)
    finally:
        con.close()


@app.get("/zonas/{codigo}/ultima", tags=["Zonas"], response_model=UltimaOcupacion,
         summary="Última ocupación de una zona",
         description="Devuelve la lectura más reciente de la zona, con porcentaje ocupado y cupos libres.",
         responses={404: {"model": ErrorRespuesta,
                          "description": "`ZONA_INEXISTENTE` o `SIN_LECTURAS`."}})
def zona_ultima(codigo: str = Path(description="Código de la zona.", examples=["BHMBCCMKT01"])):
    con = db.conectar()
    try:
        return servicio.ultima_lectura(con, codigo)
    finally:
        con.close()


# ----- Reservas -------------------------------------------------------------
@app.get("/zonas/{codigo}/disponibilidad", tags=["Reservas"], response_model=DisponibilidadZona,
         summary="Cupos disponibles para reservar en un horario",
         description="Calcula cuántos cupos quedan en la zona entre dos horas, descontando las reservas activas "
                     "que se cruzan con ese intervalo.",
         responses={404: {"model": ErrorRespuesta, "description": "`ZONA_INEXISTENTE`."},
                    422: {"model": ErrorRespuesta, "description": "Fechas inválidas o fin antes que inicio."}})
def zona_disponibilidad(
    codigo: str = Path(description="Código de la zona.", examples=["BHMBCCMKT01"]),
    inicio: str = Query(description="Inicio, `AAAA-MM-DD HH:MM:SS`.", examples=["2036-06-10 08:00:00"]),
    fin: str = Query(description="Fin, `AAAA-MM-DD HH:MM:SS`.", examples=["2036-06-10 12:00:00"]),
):
    con = db.conectar()
    try:
        return servicio.disponibilidad(con, codigo, inicio, fin)
    finally:
        con.close()


@app.post("/reservas", tags=["Reservas"], response_model=ReservaDetalle, status_code=201,
          summary="Crear una reserva",
          description=(
              "Valida la reserva con las restricciones de la zona y, si todo está bien, la guarda en la base de datos.\n\n"
              "Orden de validación: campos completos → fechas → inicio futuro → zona reservable → vehículo permitido → "
              "horario → duración → una reserva por horario por persona → límite de reservas activas → cupos libres."
          ),
          responses={404: {"model": ErrorRespuesta, "description": "`ZONA_INEXISTENTE`."},
                     409: {"model": ErrorRespuesta, "description": "Límite de reservas, solape o sin cupos."},
                     422: {"model": ErrorRespuesta, "description": "Datos o restricciones no válidas."}})
def crear_reserva(entrada: ReservaEntrada):
    con = db.conectar()
    try:
        return servicio.crear_reserva(con, entrada.model_dump())
    finally:
        con.close()


@app.get("/reservas", tags=["Reservas"], response_model=list[ReservaDetalle],
         summary="Reservas de una persona",
         description="Lista las reservas de una identificación, de la más reciente a la más antigua, activas y canceladas.")
def reservas_de_persona(identificacion: str = Query(description="Identificación de la persona.",
                                                    examples=["1001234567"])):
    con = db.conectar()
    try:
        return servicio.listar_reservas(con, identificacion)
    finally:
        con.close()


@app.post("/reservas/{reserva_id}/cancelar", tags=["Reservas"], response_model=ReservaDetalle,
          summary="Cancelar una reserva",
          description="Cambia el estado de la reserva a `cancelada` y libera el cupo.",
          responses={404: {"model": ErrorRespuesta, "description": "`RESERVA_NO_ENCONTRADA`."},
                     409: {"model": ErrorRespuesta, "description": "Ya cancelada o ya terminó."}})
def cancelar_reserva(reserva_id: int = Path(description="Identificador de la reserva.", examples=[1])):
    con = db.conectar()
    try:
        return servicio.cancelar_reserva(con, reserva_id)
    finally:
        con.close()


@app.get("/reservas/activas", tags=["Reservas"], response_model=list[ReservaDetalle],
         summary="Listar todas las reservas activas",
         description="Devuelve todas las reservas vigentes en este momento en cualquier zona de la sede.")
def reservas_activas_todas():
    con = db.conectar()
    try:
        return servicio.listar_todas_reservas_activas(con)
    finally:
        con.close()


@app.post("/reservas/{reserva_id}/ampliar", tags=["Reservas"], response_model=ReservaDetalle,
          summary="Ampliar el tiempo de una reserva",
          description="Suma minutos al fin de una reserva activa comprobando horario y cupo disponible.",
          responses={404: {"model": ErrorRespuesta, "description": "`RESERVA_NO_ENCONTRADA`."},
                     409: {"model": ErrorRespuesta, "description": "Reserva cancelada, vencida o sin cupo."},
                     422: {"model": ErrorRespuesta, "description": "Fuera de horario o duración excedida."}})
def ampliar_reserva(reserva_id: int = Path(description="Identificador de la reserva.", examples=[1]),
                    entrada: Optional[AmpliarReservaEntrada] = None):
    minutos = entrada.minutos if entrada else 30
    con = db.conectar()
    try:
        return servicio.ampliar_reserva(con, reserva_id, minutos)
    finally:
        con.close()


# ----- Seguridad e inteligencia (v6) ----------------------------------------
class ClaveEntrada(BaseModel):
    clave: Optional[Any] = Field(default=None, description="Clave de al menos 8 caracteres. Se guarda con hash.",
                                 examples=["clave-segura-2026"])


@app.post("/usuarios/{identificacion}/clave", tags=["Reservas"], summary="Guardar la clave de una persona",
          description="Guarda la clave con hash PBKDF2-SHA256 y sal. La clave nunca se devuelve ni se guarda en texto plano.",
          responses={404: {"model": ErrorRespuesta, "description": "`USUARIO_NO_ENCONTRADO`."},
                     422: {"model": ErrorRespuesta, "description": "`CLAVE_DEBIL`."}})
def guardar_clave(identificacion: str = Path(description="Identificación de la persona.", examples=["1001234567"]),
                  entrada: ClaveEntrada = None):
    con = db.conectar()
    try:
        return servicio.establecer_clave(con, identificacion, entrada.clave if entrada else None)
    finally:
        con.close()


@app.post("/usuarios/{identificacion}/verificar-clave", tags=["Reservas"], summary="Verificar la clave de una persona",
          responses={401: {"model": ErrorRespuesta, "description": "`CLAVE_INCORRECTA`."},
                     404: {"model": ErrorRespuesta, "description": "`USUARIO_NO_ENCONTRADO`."}})
def verificar_clave_persona(identificacion: str = Path(description="Identificación de la persona.",
                                                       examples=["1001234567"]),
                            entrada: ClaveEntrada = None):
    con = db.conectar()
    try:
        return servicio.verificar_clave(con, identificacion, entrada.clave if entrada else None)
    finally:
        con.close()


@app.get("/zonas/{codigo}/alerta", tags=["Zonas"], summary="Alerta de ocupación de una zona",
         description="Clasifica la última lectura como `normal`, `atencion` o `critica` con una regla fija.",
         responses={404: {"model": ErrorRespuesta, "description": "`ZONA_INEXISTENTE` o `SIN_LECTURAS`."}})
def zona_alerta(codigo: str = Path(description="Código de la zona.", examples=["BHMBCCMKT01"])):
    con = db.conectar()
    try:
        return inteligencia.alerta_zona(con, codigo)
    finally:
        con.close()


@app.get("/zonas/{codigo}/prediccion", tags=["Zonas"], summary="Predicción de ocupación para un día y hora",
         description="Estima la ocupación con el promedio histórico de esa zona para el mismo día de la semana y hora.",
         responses={404: {"model": ErrorRespuesta, "description": "`ZONA_INEXISTENTE` o `SIN_HISTORIAL`."},
                    422: {"model": ErrorRespuesta, "description": "`FECHA_INVALIDA`."}})
def zona_prediccion(codigo: str = Path(description="Código de la zona.", examples=["BHMBCCMKT01"]),
                    fecha_hora: str = Query(description="Fecha y hora, `AAAA-MM-DD HH:MM:SS`.",
                                            examples=["2016-12-22 12:00:00"])):
    con = db.conectar()
    try:
        return inteligencia.prediccion_zona(con, codigo, fecha_hora)
    finally:
        con.close()


# ----- Lecturas -------------------------------------------------------------
@app.post("/lecturas", tags=["Lecturas"], summary="Registrar una lectura de ocupación",
          description=(
              "Valida la lectura con las seis reglas y la guarda.\n\n"
              "- **201** `creada`: se guardó una lectura nueva.\n"
              "- **200** `ya_existia`: la misma lectura ya estaba en la base; no se duplica.\n"
              "- **409** `LECTURA_CONFLICTIVA`: la zona y la hora ya tienen otro valor.\n"
              "- **404** / **422**: errores de zona, formato o capacidad (ver la tabla de la descripción de la API)."
          ),
          responses={
              200: {"model": RespuestaLectura, "description": "La lectura ya existía con el mismo valor."},
              201: {"model": RespuestaLectura, "description": "Lectura creada y guardada."},
              **RESPUESTAS_ERROR_LECTURA,
          })
def crear_lectura(entrada: LecturaEntrada):
    con = db.conectar()
    try:
        estado, lectura = servicio.registrar_lectura(
            con, entrada.codigo_zona, entrada.fecha_hora, entrada.ocupacion)
    finally:
        con.close()
    return JSONResponse(status_code=201 if estado == "creada" else 200,
                        content={"estado": estado, "lectura": lectura})


# ==========================================================================
# Herramientas internas de la interfaz web (no aparecen en la documentación)
# ==========================================================================
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def raiz():
    if INDEX_HTML_PATH.exists():
        return HTMLResponse(content=INDEX_HTML_PATH.read_text(encoding="utf-8"))
    return RedirectResponse(url="/docs")


PAGINA_DOCS = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Documentación · Parqueadero inteligente universitario</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css">
  <style>
    :root { --bg:#070a12; --panel:#0f1523; --panel2:#151d2e; --line:rgba(255,255,255,.08);
            --txt:#e2e8f0; --mut:#94a3b8; --cy:#06b6d4; --in:#6366f1; --gr:#10b981; --am:#f59e0b; --ro:#f43f5e; }
    * { box-sizing: border-box; }
    body { margin:0; background:radial-gradient(1200px 500px at 10% -10%, rgba(99,102,241,.18), transparent),
           radial-gradient(900px 400px at 100% 0%, rgba(6,182,212,.14), transparent), var(--bg);
           color:var(--txt); font-family: Inter, system-ui, "Segoe UI", sans-serif; }
    .wrap { max-width: 1180px; margin: 0 auto; padding: 36px 24px 12px; }
    .hero { display:flex; flex-wrap:wrap; justify-content:space-between; gap:20px; align-items:flex-end; }
    .eyebrow { color:var(--cy); font-size:12px; letter-spacing:.16em; text-transform:uppercase; font-weight:700; }
    h1 { margin:8px 0 6px; font-size:32px; letter-spacing:-.02em; }
    .lead { color:var(--mut); max-width:640px; line-height:1.6; margin:0; }
    .badges { display:flex; gap:8px; margin-top:12px; flex-wrap:wrap; }
    .badge { font-size:12px; padding:4px 10px; border-radius:999px; border:1px solid var(--line); background:var(--panel); color:var(--mut); }
    .badge.ok { color:var(--gr); border-color:rgba(16,185,129,.35); }
    .links { display:flex; gap:10px; flex-wrap:wrap; }
    .btn { text-decoration:none; font-weight:600; font-size:14px; padding:10px 16px; border-radius:10px; border:1px solid var(--line); color:var(--txt); background:var(--panel2); }
    .btn.primary { background:linear-gradient(135deg,#0891b2,#6366f1); border-color:transparent; color:#fff; }
    .btn:hover { filter:brightness(1.15); }
    .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:14px; margin:26px 0 8px; }
    .card { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:18px; }
    .card h3 { margin:0 0 8px; font-size:15px; color:var(--cy); }
    .card p, .card li { color:var(--mut); font-size:13.5px; line-height:1.6; margin:0; }
    .card ul { margin:0; padding-left:18px; }
    .card code, .card kbd { color:#c7d2fe; background:#0b1120; padding:1px 6px; border-radius:6px; font-size:12px; }
    .errors { display:grid; grid-template-columns:auto 1fr auto; gap:6px 14px; font-size:13px; margin-top:4px; }
    .errors code { color:#fca5a5; }
    .errors span { color:var(--mut); }
    .errors b { font-weight:600; }
    .c422 { color:var(--am); } .c404 { color:var(--mut); } .c409 { color:var(--ro); }
    .sec-title { margin:30px 0 4px; font-size:13px; letter-spacing:.14em; text-transform:uppercase; color:var(--mut); }
    #swagger-ui { margin-top:10px; }
    /* ---------- Swagger UI con tema oscuro ---------- */
    .swagger-ui .topbar { display:none; }
    .swagger-ui, .swagger-ui .info .title, .swagger-ui .info p, .swagger-ui .info li,
    .swagger-ui .opblock-description-wrapper p, .swagger-ui .opblock-summary-description,
    .swagger-ui .parameter__name, .swagger-ui .parameter__type, .swagger-ui table thead tr th,
    .swagger-ui table tbody tr td, .swagger-ui .response-col_status, .swagger-ui .response-col_description,
    .swagger-ui .responses-inner h4, .swagger-ui .responses-inner h5, .swagger-ui label, .swagger-ui .tab li,
    .swagger-ui .model, .swagger-ui .model-title, .swagger-ui section.models h4, .swagger-ui .markdown p,
    .swagger-ui .markdown code, .swagger-ui .renderedMarkdown p, .swagger-ui .opblock-tag, .swagger-ui .opblock .opblock-section-header h4,
    .swagger-ui .opblock-summary-path, .swagger-ui .opblock-summary-path__deprecated { color:var(--txt) !important; }
    .swagger-ui .info .title small { background:var(--panel2); }
    .swagger-ui .info .title small pre { background:var(--panel2); color:var(--txt); }
    .swagger-ui .opblock-summary-description, .swagger-ui .parameter__in, .swagger-ui .response-col_links { color:var(--mut) !important; }
    .swagger-ui .opblock-tag { border-bottom:1px solid var(--line); }
    .swagger-ui .opblock-tag:hover { background:rgba(255,255,255,.02); }
    .swagger-ui .opblock { background:var(--panel); border-color:var(--line); box-shadow:none; border-radius:12px; }
    .swagger-ui .opblock .opblock-summary { border-color:var(--line); }
    .swagger-ui .opblock-body, .swagger-ui .opblock .opblock-section-header { background:var(--panel2); }
    .swagger-ui .opblock.opblock-get { background:rgba(6,182,212,.07); border-color:rgba(6,182,212,.3); }
    .swagger-ui .opblock.opblock-post { background:rgba(16,185,129,.07); border-color:rgba(16,185,129,.3); }
    .swagger-ui .opblock.opblock-get .opblock-summary-method { background:#0891b2; }
    .swagger-ui .opblock.opblock-post .opblock-summary-method { background:#059669; }
    .swagger-ui .opblock-summary-path { font-family: Consolas, Menlo, monospace; }
    .swagger-ui .scheme-container { background:var(--panel); box-shadow:none; border:1px solid var(--line); border-radius:12px; margin-bottom:12px; }
    .swagger-ui select, .swagger-ui input[type=text], .swagger-ui input[type=search], .swagger-ui input[type=password], .swagger-ui textarea {
      background:#0b1120 !important; color:var(--txt) !important; border:1px solid #334155 !important; border-radius:8px; }
    .swagger-ui .btn { border-radius:8px; }
    .swagger-ui .btn.execute { background:#0891b2; border-color:#0891b2; }
    .swagger-ui .btn.try-out__btn, .swagger-ui .btn.cancel { border-color:#334155; color:var(--txt); background:transparent; }
    .swagger-ui .response-col_status--200 .response-undocumented { color:var(--gr); }
    .swagger-ui .responses-inner { background:transparent; }
    .swagger-ui .highlight-code, .swagger-ui .microlight, .swagger-ui .highlight-code > .microlight {
      background:#0b1120 !important; color:#e2e8f0 !important; border-radius:8px; }
    .swagger-ui .model-box, .swagger-ui section.models { background:var(--panel); border:1px solid var(--line); border-radius:12px; box-shadow:none; }
    .swagger-ui section.models.is-open h4 { border-bottom:1px solid var(--line); }
    .swagger-ui .model .property.primitive, .swagger-ui .prop-format, .swagger-ui .model-toggle:after { color:var(--mut) !important; }
    .swagger-ui .opblock-tag-section h3 a span, .swagger-ui .opblock-tag small { color:var(--mut) !important; }
    .swagger-ui svg:not(:root) { fill: currentColor; }
    .swagger-ui .arrow { fill:var(--txt); }
    .swagger-ui .expand-operation svg, .swagger-ui .authorization__btn svg { fill:var(--mut); }
    @media (max-width:600px) { h1 { font-size:24px; } }
  </style>
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <div>
        <div class="eyebrow">API · Entrega E2</div>
        <h1>Parqueadero inteligente universitario</h1>
        <p class="lead">Recibe lecturas de ocupación de zonas de parqueo, las valida, las guarda y permite consultarlas.
          Esta página es la documentación interactiva: puedes leer cada endpoint y probarlo directamente.</p>
        <div class="badges">
          <span class="badge">Versión 2.0.0</span>
          <span class="badge">OpenAPI 3.1</span>
          <span class="badge ok">API en línea</span>
        </div>
      </div>
      <nav class="links">
        <a class="btn primary" href="/">Abrir la aplicación</a>
        <a class="btn" href="/redoc">Ver en ReDoc</a>
        <a class="btn" href="/openapi.json">openapi.json</a>
      </nav>
    </header>

    <section class="cards">
      <div class="card">
        <h3>Cómo probar un endpoint</h3>
        <ul>
          <li>Haz clic en la ruta para abrirla.</li>
          <li>Pulsa <kbd>Try it out</kbd> y llena los campos.</li>
          <li>Pulsa <kbd>Execute</kbd> y mira la respuesta abajo.</li>
        </ul>
      </div>
      <div class="card">
        <h3>Orden recomendado</h3>
        <ul>
          <li><code>GET /zonas</code> para ver los códigos válidos.</li>
          <li><code>POST /lecturas</code> para enviar una lectura.</li>
          <li><code>GET /zonas/{codigo}/ultima</code> para verla reflejada.</li>
        </ul>
      </div>
      <div class="card">
        <h3>Idempotencia</h3>
        <p>Enviar la <b>misma</b> lectura dos veces no crea un duplicado: la segunda responde <code>200</code> con <code>ya_existia</code>.
           Enviar otro valor para la misma zona y hora responde <code>409</code>.</p>
      </div>
      <div class="card">
        <h3>Códigos de error</h3>
        <div class="errors">
          <b class="c422">422</b><span>Formato o regla de negocio</span><code>OCUPACION_SUPERA_CAPACIDAD</code>
          <b class="c404">404</b><span>Zona no existe o sin lecturas</span><code>ZONA_INEXISTENTE</code>
          <b class="c409">409</b><span>Conflicto con otro valor</span><code>LECTURA_CONFLICTIVA</code>
        </div>
      </div>
    </section>

    <div class="sec-title">Endpoints</div>
  </div>
  <div class="wrap" style="padding-top:0"><div id="swagger-ui"></div></div>

  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: "/openapi.json",
      dom_id: "#swagger-ui",
      deepLinking: true,
      tryItOutEnabled: true,
      defaultModelsExpandDepth: -1,
      docExpansion: "list",
      displayRequestDuration: true,
      filter: true,
      persistAuthorization: false
    });
  </script>
</body>
</html>
"""

PAGINA_REDOC = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ReDoc · Parqueadero inteligente universitario</title>
  <style>body { margin: 0; background: #070a12; }</style>
</head>
<body>
  <redoc spec-url="/openapi.json" theme='__TEMA__'></redoc>
  <script src="https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js"></script>
</body>
</html>
"""


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
def documentacion_swagger():
    return HTMLResponse(content=PAGINA_DOCS)


@app.get("/redoc", response_class=HTMLResponse, include_in_schema=False)
def documentacion_redoc():
    return HTMLResponse(content=PAGINA_REDOC.replace("__TEMA__", json.dumps(REDOC_TEMA)))


RESULTADO_RE = re.compile(r"^(tests[\\/][\w./\\-]+\.py)::(.+?)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")
DURACION_RE = re.compile(r"in ([\d.]+)s")


def _pytest(args):
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=str(RAIZ), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _leer_json(ruta):
    """Lee un JSON que pudo guardarse en UTF-8 o en UTF-16 (PowerShell usa UTF-16 con '>')."""
    if not ruta.exists():
        return None
    crudo = ruta.read_bytes()
    for codificacion in ("utf-8-sig", "utf-16"):
        try:
            return json.loads(crudo.decode(codificacion))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


@app.get("/api/pruebas", include_in_schema=False)
def listar_pruebas():
    """Lista las pruebas sin ejecutarlas, agrupadas por archivo."""
    res = _pytest(["--collect-only", "-q"])
    archivos = {}
    for linea in res.stdout.splitlines():
        m = re.match(r"^(tests[\\/][\w./\\-]+\.py)::(.+)$", linea.strip())
        if m:
            archivo = m.group(1).replace("\\", "/")
            archivos.setdefault(archivo, []).append(m.group(2))
    return {"archivos": [{"archivo": a, "pruebas": n, "total": len(n)} for a, n in archivos.items()],
            "total": sum(len(n) for n in archivos.values())}


@app.post("/api/run-tests", include_in_schema=False)
def correr_pruebas():
    """Ejecuta pytest -v y devuelve el resultado por prueba y el resumen."""
    res = _pytest(["-v"])
    archivos, pasadas, fallidas, duracion = {}, 0, 0, None
    for linea in res.stdout.splitlines():
        m = RESULTADO_RE.match(linea.strip())
        if m:
            archivo = m.group(1).replace("\\", "/")
            estado = m.group(3)
            bloque = archivos.setdefault(archivo, {"total": 0, "passed": 0, "failed": 0, "pruebas": []})
            bloque["total"] += 1
            bloque["passed" if estado == "PASSED" else "failed"] += 1
            bloque["pruebas"].append({"nombre": m.group(2), "estado": estado})
            if estado == "PASSED":
                pasadas += 1
            else:
                fallidas += 1
        if duracion is None and re.search(r"\d+ (passed|failed|error)", linea):
            d = DURACION_RE.search(linea)
            duracion = d.group(1) if d else None
    return {
        "codigo": res.returncode,
        "resumen": {"passed": pasadas, "failed": fallidas, "duracion_s": duracion},
        "archivos": archivos,
        "output": res.stdout or res.stderr,
    }


@app.get("/api/pipeline", include_in_schema=False)
def resumen_pipeline():
    """Reconciliaciones guardadas por el pipeline y conteos vivos de la base."""
    salidas = RAIZ / "salidas"
    reconciliaciones = {}
    for nombre in ("datos_originales", "anomalias_prueba"):
        ruta = salidas / f"reconciliacion_{nombre}.json"
        if ruta.exists():
            reconciliaciones[nombre] = json.loads(ruta.read_text(encoding="utf-8"))
    con = db.conectar()
    try:
        lecturas = con.execute("SELECT COUNT(*) AS n FROM lectura_ocupacion").fetchone()["n"]
        zonas_n = con.execute("SELECT COUNT(*) AS n FROM zona").fetchone()["n"]
    finally:
        con.close()
    corridas = {
        "carga_inicial": _leer_json(RAIZ / "evidencias" / "01_carga_inicial.json"),
        "segunda_ejecucion": _leer_json(RAIZ / "evidencias" / "02_segunda_ejecucion.json"),
        "anomalias": _leer_json(RAIZ / "evidencias" / "03_anomalias.json"),
    }
    return {"reconciliaciones": reconciliaciones, "corridas": corridas,
            "lecturas_en_bd": lecturas, "zonas_en_catalogo": zonas_n}
