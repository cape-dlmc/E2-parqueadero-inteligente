"""Inteligencia de la aplicación, con datos propios de la base.

1) Alerta por reglas (determinista): si la última lectura supera un umbral, la zona se marca.
   Basta con una regla porque el criterio es claro y no necesita aprender de datos.
2) Predicción con promedio histórico por día de la semana y hora (modelo estadístico simple).
   Es un primer modelo aprendido de los datos de la propia base; no reemplaza un modelo
   entrenado con más variables (clima, eventos, festivos).
"""
from app import reglas, servicio

UMBRAL_CRITICO = 90      # % ocupado: zona casi llena
UMBRAL_ATENCION = 70     # % ocupado: poca disponibilidad
DIAS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"]


def alerta_zona(con, codigo):
    ultima = servicio.ultima_lectura(con, codigo)     # lanza ZONA_INEXISTENTE o SIN_LECTURAS
    pct = ultima["porcentaje_ocupado"]
    if pct >= UMBRAL_CRITICO:
        nivel, mensaje = "critica", "Zona casi llena: queda menos del 10 % libre"
    elif pct >= UMBRAL_ATENCION:
        nivel, mensaje = "atencion", "Zona con poca disponibilidad"
    else:
        nivel, mensaje = "normal", "Hay cupos suficientes"
    return {
        "codigo_zona": codigo,
        "nivel": nivel,
        "mensaje": mensaje,
        "porcentaje_ocupado": pct,
        "fecha_hora": ultima["fecha_hora"],
        "regla": f"critica si ≥ {UMBRAL_CRITICO} %, atencion si ≥ {UMBRAL_ATENCION} %",
    }


def prediccion_zona(con, codigo, fecha_hora):
    zona = con.execute("SELECT capacidad FROM zona WHERE codigo_zona = ?", (codigo,)).fetchone()
    if zona is None:
        raise reglas.ErrorValidacion(reglas.ZONA_INEXISTENTE, f"La zona '{codigo}' no existe", "codigo")
    fecha = servicio._fecha(fecha_hora, "fecha_hora")
    dia, hora = fecha.strftime("%w"), fecha.strftime("%H")
    fila = con.execute(
        "SELECT AVG(ocupacion) AS promedio, COUNT(*) AS muestras FROM lectura_ocupacion "
        "WHERE codigo_zona = ? AND strftime('%w', fecha_hora) = ? AND strftime('%H', fecha_hora) = ?",
        (codigo, dia, hora)).fetchone()
    if not fila["muestras"]:
        raise reglas.ErrorValidacion(reglas.SIN_HISTORIAL,
                                     f"No hay lecturas históricas de esa zona para {DIAS[int(dia)]} a las {hora} h",
                                     "fecha_hora")
    estimado = round(fila["promedio"])
    capacidad = zona["capacidad"]
    return {
        "codigo_zona": codigo,
        "fecha_hora": fecha.strftime(servicio.FORMATO_FECHA),
        "dia_semana": DIAS[int(dia)],
        "ocupacion_estimada": estimado,
        "porcentaje_estimado": round(100.0 * estimado / capacidad, 1),
        "cupos_libres_estimados": capacidad - estimado,
        "muestras_historicas": fila["muestras"],
        "metodo": "promedio histórico por día de la semana y hora",
    }
