"""Reglas de validación compartidas por la API y por el pipeline.

Es la única fuente de verdad: si una lectura se rechaza en la API, se rechaza
igual en el pipeline, y el código de error es el mismo en ambos lados.
"""
import re
from datetime import datetime

FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"

# Códigos de error estables
CAMPO_INCOMPLETO = "CAMPO_INCOMPLETO"
CAMPO_INVALIDO = "CAMPO_INVALIDO"
FECHA_INVALIDA = "FECHA_INVALIDA"
ZONA_INEXISTENTE = "ZONA_INEXISTENTE"
OCUPACION_NEGATIVA = "OCUPACION_NEGATIVA"
OCUPACION_SUPERA_CAPACIDAD = "OCUPACION_SUPERA_CAPACIDAD"
LECTURA_CONFLICTIVA = "LECTURA_CONFLICTIVA"
SIN_LECTURAS = "SIN_LECTURAS"
JSON_INVALIDO = "JSON_INVALIDO"
SIN_HISTORIAL = "SIN_HISTORIAL"
TEXTO_PELIGROSO = "TEXTO_PELIGROSO"
CLAVE_DEBIL = "CLAVE_DEBIL"
USUARIO_NO_ENCONTRADO = "USUARIO_NO_ENCONTRADO"
CLAVE_INCORRECTA = "CLAVE_INCORRECTA"

# Códigos de reservas
RANGO_INVALIDO = "RANGO_INVALIDO"
RESERVA_EN_PASADO = "RESERVA_EN_PASADO"
ZONA_NO_RESERVABLE = "ZONA_NO_RESERVABLE"
TIPO_NO_PERMITIDO = "TIPO_NO_PERMITIDO"
FUERA_DE_HORARIO = "FUERA_DE_HORARIO"
DURACION_EXCEDIDA = "DURACION_EXCEDIDA"
LIMITE_RESERVAS_USUARIO = "LIMITE_RESERVAS_USUARIO"
USUARIO_CON_RESERVA_SOLAPADA = "USUARIO_CON_RESERVA_SOLAPADA"
SIN_CUPOS_RESERVA = "SIN_CUPOS_RESERVA"
RESERVA_NO_ENCONTRADA = "RESERVA_NO_ENCONTRADA"
RESERVA_YA_CANCELADA = "RESERVA_YA_CANCELADA"
RESERVA_VENCIDA = "RESERVA_VENCIDA"

HTTP_POR_CODIGO = {
    ZONA_INEXISTENTE: 404,
    SIN_LECTURAS: 404,
    LECTURA_CONFLICTIVA: 409,
    CAMPO_INCOMPLETO: 422,
    CAMPO_INVALIDO: 422,
    FECHA_INVALIDA: 422,
    OCUPACION_NEGATIVA: 422,
    OCUPACION_SUPERA_CAPACIDAD: 422,
    JSON_INVALIDO: 422,
    RANGO_INVALIDO: 422,
    RESERVA_EN_PASADO: 422,
    ZONA_NO_RESERVABLE: 422,
    TIPO_NO_PERMITIDO: 422,
    FUERA_DE_HORARIO: 422,
    DURACION_EXCEDIDA: 422,
    LIMITE_RESERVAS_USUARIO: 409,
    USUARIO_CON_RESERVA_SOLAPADA: 409,
    SIN_CUPOS_RESERVA: 409,
    RESERVA_NO_ENCONTRADA: 404,
    RESERVA_YA_CANCELADA: 409,
    RESERVA_VENCIDA: 409,
    SIN_HISTORIAL: 404,
    TEXTO_PELIGROSO: 422,
    CLAVE_DEBIL: 422,
    USUARIO_NO_ENCONTRADO: 404,
    CLAVE_INCORRECTA: 401,
}


class ErrorValidacion(Exception):
    def __init__(self, codigo, mensaje, campo=None):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.campo = campo


def _vacio(valor):
    return valor is None or (isinstance(valor, str) and valor.strip() == "")


def validar_lectura(codigo_zona, fecha_hora, ocupacion, capacidad_zona):
    """Valida una lectura y devuelve sus valores normalizados.

    capacidad_zona: capacidad de la zona según el catálogo, o None si la zona no existe.
    Orden de las reglas (fijo): 1) campos completos 2) formato de fecha
    3) ocupación entera 4) ocupación no negativa 5) zona existente 6) ocupación <= capacidad.
    """
    if _vacio(codigo_zona):
        raise ErrorValidacion(CAMPO_INCOMPLETO, "Falta codigo_zona", "codigo_zona")
    if _vacio(fecha_hora):
        raise ErrorValidacion(CAMPO_INCOMPLETO, "Falta fecha_hora", "fecha_hora")
    if _vacio(ocupacion):
        raise ErrorValidacion(CAMPO_INCOMPLETO, "Falta ocupacion", "ocupacion")

    codigo = str(codigo_zona).strip()
    fecha = str(fecha_hora).strip()
    try:
        datetime.strptime(fecha, FORMATO_FECHA)
    except ValueError:
        raise ErrorValidacion(FECHA_INVALIDA,
                              f"fecha_hora debe tener el formato AAAA-MM-DD HH:MM:SS", "fecha_hora")

    if isinstance(ocupacion, bool) or not re.fullmatch(r"-?\d+", str(ocupacion).strip()):
        raise ErrorValidacion(CAMPO_INVALIDO, "ocupacion debe ser un número entero", "ocupacion")
    ocup = int(str(ocupacion).strip())

    if ocup < 0:
        raise ErrorValidacion(OCUPACION_NEGATIVA, "ocupacion no puede ser negativa", "ocupacion")
    if capacidad_zona is None:
        raise ErrorValidacion(ZONA_INEXISTENTE, f"La zona '{codigo}' no existe", "codigo_zona")
    if ocup > capacidad_zona:
        raise ErrorValidacion(OCUPACION_SUPERA_CAPACIDAD,
                              f"ocupacion {ocup} supera la capacidad {capacidad_zona} de la zona",
                              "ocupacion")
    return {"codigo_zona": codigo, "fecha_hora": fecha, "ocupacion": ocup}
