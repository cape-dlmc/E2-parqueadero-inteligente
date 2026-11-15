"""Lógica de negocio de la API: lecturas de ocupación, zonas, restricciones y reservas."""
from datetime import datetime, timedelta, timezone

from app import reglas, seguridad

# Montería (Colombia) usa UTC-5 todo el año: no tiene horario de verano.
ZONA_SEDE = timezone(timedelta(hours=-5))
FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"
TIPOS_VEHICULO = ("carro", "moto")

SQL_ULTIMA_OCUPACION = """
WITH ultima AS (
    SELECT codigo_zona, MAX(fecha_hora) AS fecha_hora
    FROM lectura_ocupacion GROUP BY codigo_zona
)
SELECT z.codigo_zona, z.capacidad, l.fecha_hora, l.ocupacion,
       ROUND(100.0 * l.ocupacion / z.capacidad, 1) AS porcentaje_ocupado,
       z.capacidad - l.ocupacion AS cupos_libres
FROM ultima u
JOIN lectura_ocupacion l ON l.codigo_zona = u.codigo_zona AND l.fecha_hora = u.fecha_hora
JOIN zona z ON z.codigo_zona = l.codigo_zona
ORDER BY porcentaje_ocupado ASC, z.codigo_zona ASC
"""

SQL_ZONA_DETALLE = """
SELECT z.codigo_zona, z.capacidad,
       COALESCE(u.nombre, z.codigo_zona)            AS nombre,
       COALESCE(u.sector, 'Sin sector')             AS sector,
       COALESCE(u.x, 0)                             AS x,
       COALESCE(u.y, 0)                             AS y,
       COALESCE(r.reservable, 1)                    AS reservable,
       COALESCE(r.tipos_permitidos, 'carro,moto')   AS tipos_permitidos,
       COALESCE(r.hora_apertura, '06:00')           AS hora_apertura,
       COALESCE(r.hora_cierre, '22:00')             AS hora_cierre,
       COALESCE(r.max_horas_reserva, 8)             AS max_horas_reserva,
       COALESCE(r.max_reservas_activas_usuario, 2)  AS max_reservas_activas_usuario,
       COALESCE(r.nota, '')                         AS nota
FROM zona z
LEFT JOIN zona_ubicacion u ON u.codigo_zona = z.codigo_zona
LEFT JOIN restriccion_zona r ON r.codigo_zona = z.codigo_zona
"""


# ==========================================================================
# Utilidades
# ==========================================================================
def ahora_sede():
    """Hora actual en Montería, sin zona horaria (para comparar con las fechas de la base)."""
    return datetime.now(ZONA_SEDE).replace(tzinfo=None)


def _vacio(valor):
    return valor is None or (isinstance(valor, str) and valor.strip() == "")


def _fecha(valor, campo):
    if _vacio(valor):
        raise reglas.ErrorValidacion(reglas.CAMPO_INCOMPLETO, f"Falta {campo}", campo)
    try:
        return datetime.strptime(str(valor).strip(), FORMATO_FECHA)
    except ValueError:
        raise reglas.ErrorValidacion(reglas.FECHA_INVALIDA,
                                     f"{campo} debe tener el formato AAAA-MM-DD HH:MM:SS", campo)


def _detalle_zona(fila):
    d = dict(fila)
    d["reservable"] = bool(d["reservable"])
    d["tipos_permitidos"] = [t for t in d["tipos_permitidos"].split(",") if t]
    d["horario"] = f"{d['hora_apertura']} – {d['hora_cierre']}"
    return d


# ==========================================================================
# Lecturas de ocupación (sin cambios de comportamiento)
# ==========================================================================
def _capacidad_de(con, codigo):
    if codigo is None or str(codigo).strip() == "":
        return None
    fila = con.execute("SELECT capacidad FROM zona WHERE codigo_zona = ?",
                       (str(codigo).strip(),)).fetchone()
    return fila["capacidad"] if fila else None


def registrar_lectura(con, codigo_zona, fecha_hora, ocupacion):
    """Devuelve ('creada' | 'ya_existia', lectura). Lanza ErrorValidacion si no se puede."""
    capacidad = _capacidad_de(con, codigo_zona)
    lectura = reglas.validar_lectura(codigo_zona, fecha_hora, ocupacion, capacidad)

    existente = con.execute(
        "SELECT ocupacion FROM lectura_ocupacion WHERE codigo_zona = ? AND fecha_hora = ?",
        (lectura["codigo_zona"], lectura["fecha_hora"])).fetchone()
    if existente is not None:
        if existente["ocupacion"] == lectura["ocupacion"]:
            return "ya_existia", lectura
        raise reglas.ErrorValidacion(
            reglas.LECTURA_CONFLICTIVA,
            f"Ya existe una lectura de esa zona a esa hora con ocupacion {existente['ocupacion']}",
            "fecha_hora")

    con.execute(
        "INSERT INTO lectura_ocupacion (codigo_zona, fecha_hora, ocupacion) VALUES (?, ?, ?)",
        (lectura["codigo_zona"], lectura["fecha_hora"], lectura["ocupacion"]))
    con.commit()
    return "creada", lectura


def ultima_lectura(con, codigo):
    zona = con.execute("SELECT codigo_zona, capacidad FROM zona WHERE codigo_zona = ?",
                       (codigo,)).fetchone()
    if zona is None:
        raise reglas.ErrorValidacion(reglas.ZONA_INEXISTENTE, f"La zona '{codigo}' no existe", "codigo")
    fila = con.execute(
        "SELECT fecha_hora, ocupacion FROM lectura_ocupacion WHERE codigo_zona = ? "
        "ORDER BY fecha_hora DESC LIMIT 1", (codigo,)).fetchone()
    if fila is None:
        raise reglas.ErrorValidacion(reglas.SIN_LECTURAS, f"La zona '{codigo}' aún no tiene lecturas")
    return {
        "codigo_zona": codigo,
        "capacidad": zona["capacidad"],
        "fecha_hora": fila["fecha_hora"],
        "ocupacion": fila["ocupacion"],
        "porcentaje_ocupado": round(100.0 * fila["ocupacion"] / zona["capacidad"], 1),
        "cupos_libres": zona["capacidad"] - fila["ocupacion"],
    }


def recomendadas(con, limite=5):
    return [dict(f) for f in con.execute(SQL_ULTIMA_OCUPACION + " LIMIT ?", (limite,)).fetchall()]


# ==========================================================================
# Sedes y zonas
# ==========================================================================
def listar_sedes(con):
    return [dict(f) for f in con.execute(
        "SELECT id, nombre, ciudad, departamento, latitud, longitud FROM sede ORDER BY id").fetchall()]


def listar_zonas(con):
    ahora_s = ahora_sede().strftime(FORMATO_FECHA)
    zonas = [_detalle_zona(f) for f in con.execute(SQL_ZONA_DETALLE + " ORDER BY z.codigo_zona").fetchall()]
    try:
        filas = con.execute(
            "SELECT codigo_zona, COUNT(*) AS c FROM reserva WHERE estado = 'activa' AND fin > ? GROUP BY codigo_zona",
            (ahora_s,)
        ).fetchall()
        conteos = {r["codigo_zona"]: r["c"] for r in filas}
    except Exception:
        conteos = {}
    for z in zonas:
        z["reservas_activas"] = conteos.get(z["codigo_zona"], 0)
        z["cupos_disponibles"] = max(0, z["capacidad"] - z["reservas_activas"])
    return zonas


def detalle_zona(con, codigo):
    fila = con.execute(SQL_ZONA_DETALLE + " WHERE z.codigo_zona = ?", (codigo,)).fetchone()
    if fila is None:
        raise reglas.ErrorValidacion(reglas.ZONA_INEXISTENTE, f"La zona '{codigo}' no existe", "codigo")
    d = _detalle_zona(fila)
    ahora_s = ahora_sede().strftime(FORMATO_FECHA)
    try:
        conteo = con.execute(
            "SELECT COUNT(*) AS c FROM reserva WHERE codigo_zona = ? AND estado = 'activa' AND fin > ?",
            (codigo, ahora_s)
        ).fetchone()
        d["reservas_activas"] = conteo["c"] if conteo else 0
    except Exception:
        d["reservas_activas"] = 0
    d["cupos_disponibles"] = max(0, d["capacidad"] - d["reservas_activas"])
    return d


def modificar_restricciones_zona(con, codigo, cambios):
    detalle_zona(con, codigo)
    campos_upd = []
    valores = []
    if "reservable" in cambios and cambios["reservable"] is not None:
        campos_upd.append("reservable = ?")
        valores.append(1 if cambios["reservable"] else 0)
    if "tipos_permitidos" in cambios and cambios["tipos_permitidos"] is not None:
        campos_upd.append("tipos_permitidos = ?")
        valores.append(",".join(cambios["tipos_permitidos"]))
    if "hora_apertura" in cambios and cambios["hora_apertura"] is not None:
        campos_upd.append("hora_apertura = ?")
        valores.append(str(cambios["hora_apertura"]).strip())
    if "hora_cierre" in cambios and cambios["hora_cierre"] is not None:
        campos_upd.append("hora_cierre = ?")
        valores.append(str(cambios["hora_cierre"]).strip())
    if "max_horas_reserva" in cambios and cambios["max_horas_reserva"] is not None:
        campos_upd.append("max_horas_reserva = ?")
        valores.append(int(cambios["max_horas_reserva"]))
    if "nota" in cambios and cambios["nota"] is not None:
        campos_upd.append("nota = ?")
        valores.append(str(cambios["nota"]).strip())

    if campos_upd:
        valores.append(codigo)
        con.execute(f"UPDATE restriccion_zona SET {', '.join(campos_upd)} WHERE codigo_zona = ?", tuple(valores))
        con.commit()
    return detalle_zona(con, codigo)


def resumen_admin(con):
    ahora_s = ahora_sede().strftime(FORMATO_FECHA)
    total_zonas = con.execute("SELECT COUNT(*) FROM zona").fetchone()[0]
    capacidad = con.execute("SELECT SUM(capacidad) FROM zona").fetchone()[0] or 0
    reservables = con.execute("SELECT COUNT(*) FROM restriccion_zona WHERE reservable = 1").fetchone()[0]
    total_lecturas = con.execute("SELECT COUNT(*) FROM lectura_ocupacion").fetchone()[0]
    total_reservas = con.execute("SELECT COUNT(*) FROM reserva").fetchone()[0]
    reservas_activas = con.execute("SELECT COUNT(*) FROM reserva WHERE estado = 'activa' AND fin > ?", (ahora_s,)).fetchone()[0]
    reservas_canceladas = con.execute("SELECT COUNT(*) FROM reserva WHERE estado = 'cancelada'").fetchone()[0]

    zonas_con_res = con.execute(
        "SELECT codigo_zona, COUNT(*) as activas FROM reserva WHERE estado = 'activa' AND fin > ? GROUP BY codigo_zona",
        (ahora_s,)
    ).fetchall()
    top_ocupadas = [{"codigo_zona": r["codigo_zona"], "activas": r["activas"]} for r in zonas_con_res]

    return {
        "total_zonas": total_zonas,
        "capacidad_total": capacidad,
        "zonas_reservables": reservables,
        "zonas_no_reservables": total_zonas - reservables,
        "total_lecturas": total_lecturas,
        "total_reservas": total_reservas,
        "reservas_activas": reservas_activas,
        "reservas_canceladas": reservas_canceladas,
        "top_ocupadas": top_ocupadas,
    }


# ==========================================================================
# Reservas
# ==========================================================================
def _reservas_solapadas_zona(con, codigo, inicio, fin):
    return con.execute(
        "SELECT COUNT(*) FROM reserva WHERE codigo_zona = ? AND estado = 'activa' "
        "AND inicio < ? AND fin > ?", (codigo, fin, inicio)).fetchone()[0]


def disponibilidad(con, codigo, inicio, fin):
    """Cupos que quedan para reservar en la zona durante el intervalo.

    Solo cuentan las reservas activas que se cruzan con el intervalo. Las lecturas
    históricas no se usan aquí porque describen el pasado, no el momento de la reserva.
    """
    ini = _fecha(inicio, "inicio")
    fi = _fecha(fin, "fin")
    if ini >= fi:
        raise reglas.ErrorValidacion(reglas.RANGO_INVALIDO, "fin debe ser posterior a inicio", "fin")
    zona = detalle_zona(con, codigo)
    cruzadas = _reservas_solapadas_zona(con, codigo, ini.strftime(FORMATO_FECHA), fi.strftime(FORMATO_FECHA))
    return {
        "codigo_zona": codigo,
        "inicio": ini.strftime(FORMATO_FECHA),
        "fin": fi.strftime(FORMATO_FECHA),
        "capacidad": zona["capacidad"],
        "reservas_que_se_cruzan": cruzadas,
        "cupos_para_reservar": zona["capacidad"] - cruzadas,
        "reservable": zona["reservable"],
    }


def crear_reserva(con, entrada):
    """Valida y guarda una reserva. Todo ocurre en una transacción con bloqueo de escritura."""
    for campo in ("identificacion", "nombre", "tipo_vehiculo", "codigo_zona", "inicio", "fin"):
        if _vacio(entrada.get(campo)):
            raise reglas.ErrorValidacion(reglas.CAMPO_INCOMPLETO, f"Falta {campo}", campo)

    for campo in ("nombre", "placa"):
        if not seguridad.texto_seguro(entrada.get(campo) or ""):
            raise reglas.ErrorValidacion(reglas.TEXTO_PELIGROSO,
                                         f"{campo} contiene caracteres no permitidos (etiquetas o código)", campo)

    identificacion = str(entrada["identificacion"]).strip()
    nombre = str(entrada["nombre"]).strip()
    tipo = str(entrada["tipo_vehiculo"]).strip().lower()
    codigo = str(entrada["codigo_zona"]).strip()
    placa = str(entrada.get("placa") or "").strip().upper()

    ini = _fecha(entrada["inicio"], "inicio")
    fi = _fecha(entrada["fin"], "fin")
    if ini >= fi:
        raise reglas.ErrorValidacion(reglas.RANGO_INVALIDO, "fin debe ser posterior a inicio", "fin")
    ahora = ahora_sede()
    if ini < ahora:
        raise reglas.ErrorValidacion(reglas.RESERVA_EN_PASADO,
                                     "La reserva debe empezar en el futuro (hora de Montería)", "inicio")
    if tipo not in TIPOS_VEHICULO:
        raise reglas.ErrorValidacion(reglas.CAMPO_INVALIDO, "tipo_vehiculo debe ser 'carro' o 'moto'",
                                     "tipo_vehiculo")

    zona = detalle_zona(con, codigo)   # lanza ZONA_INEXISTENTE
    if not zona["reservable"]:
        motivo = f" ({zona['nota']})" if zona["nota"] else ""
        raise reglas.ErrorValidacion(reglas.ZONA_NO_RESERVABLE,
                                     f"La zona '{zona['nombre']}' no admite reservas{motivo}", "codigo_zona")
    if tipo not in zona["tipos_permitidos"]:
        raise reglas.ErrorValidacion(
            reglas.TIPO_NO_PERMITIDO,
            f"En '{zona['nombre']}' solo se permite: {', '.join(zona['tipos_permitidos'])}", "tipo_vehiculo")
    if (ini.date() != fi.date()
            or ini.strftime("%H:%M") < zona["hora_apertura"]
            or fi.strftime("%H:%M") > zona["hora_cierre"]):
        raise reglas.ErrorValidacion(
            reglas.FUERA_DE_HORARIO,
            f"'{zona['nombre']}' solo acepta reservas entre {zona['hora_apertura']} y {zona['hora_cierre']}, "
            "dentro del mismo día", "inicio")
    horas = (fi - ini).total_seconds() / 3600
    if horas > zona["max_horas_reserva"]:
        raise reglas.ErrorValidacion(
            reglas.DURACION_EXCEDIDA,
            f"La reserva dura {horas:g} h y el máximo en esta zona es {zona['max_horas_reserva']} h", "fin")

    ini_s, fin_s, ahora_s = ini.strftime(FORMATO_FECHA), fi.strftime(FORMATO_FECHA), ahora.strftime(FORMATO_FECHA)
    con.isolation_level = None
    con.execute("BEGIN IMMEDIATE")   # bloquea escrituras: dos reservas no pueden tomar el mismo cupo
    try:
        solape_usuario = con.execute(
            "SELECT COUNT(*) FROM reserva WHERE identificacion = ? AND estado = 'activa' "
            "AND inicio < ? AND fin > ?", (identificacion, fin_s, ini_s)).fetchone()[0]
        if solape_usuario:
            raise reglas.ErrorValidacion(reglas.USUARIO_CON_RESERVA_SOLAPADA,
                                         "Ya tienes otra reserva activa en ese horario", "inicio")

        activas = con.execute(
            "SELECT COUNT(*) FROM reserva WHERE identificacion = ? AND estado = 'activa' AND fin > ?",
            (identificacion, ahora_s)).fetchone()[0]
        if activas >= zona["max_reservas_activas_usuario"]:
            raise reglas.ErrorValidacion(
                reglas.LIMITE_RESERVAS_USUARIO,
                f"Ya tienes {activas} reserva(s) activa(s); el máximo para esta zona es "
                f"{zona['max_reservas_activas_usuario']}", "identificacion")

        if zona["capacidad"] - _reservas_solapadas_zona(con, codigo, ini_s, fin_s) <= 0:
            raise reglas.ErrorValidacion(reglas.SIN_CUPOS_RESERVA,
                                         f"'{zona['nombre']}' no tiene cupos libres en ese horario", "inicio")

        con.execute(
            "INSERT INTO usuario (identificacion, nombre, tipo_vehiculo, placa) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(identificacion) DO UPDATE SET nombre = excluded.nombre, "
            "tipo_vehiculo = excluded.tipo_vehiculo, placa = excluded.placa",
            (identificacion, nombre, tipo, placa))
        cur = con.execute(
            "INSERT INTO reserva (codigo_zona, identificacion, inicio, fin, estado, creada_en) "
            "VALUES (?, ?, ?, ?, 'activa', ?)",
            (codigo, identificacion, ini_s, fin_s, ahora_s))
        reserva_id = cur.lastrowid
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.isolation_level = ""

    return obtener_reserva(con, reserva_id)


def obtener_reserva(con, reserva_id):
    fila = con.execute(
        "SELECT r.id, r.codigo_zona, COALESCE(u.nombre, r.codigo_zona) AS zona_nombre, "
        "r.identificacion, COALESCE(p.nombre, '') AS nombre, COALESCE(p.tipo_vehiculo, '') AS tipo_vehiculo, "
        "r.inicio, r.fin, r.estado, r.creada_en "
        "FROM reserva r "
        "LEFT JOIN zona_ubicacion u ON u.codigo_zona = r.codigo_zona "
        "LEFT JOIN usuario p ON p.identificacion = r.identificacion "
        "WHERE r.id = ?", (reserva_id,)).fetchone()
    if fila is None:
        raise reglas.ErrorValidacion(reglas.RESERVA_NO_ENCONTRADA, f"No existe la reserva {reserva_id}", "id")
    return dict(fila)


def listar_reservas(con, identificacion):
    ids = [r["id"] for r in con.execute(
        "SELECT id FROM reserva WHERE identificacion = ? ORDER BY inicio DESC, id DESC",
        (str(identificacion).strip(),)).fetchall()]
    return [obtener_reserva(con, i) for i in ids]


def cancelar_reserva(con, reserva_id):
    actual = obtener_reserva(con, reserva_id)     # lanza RESERVA_NO_ENCONTRADA
    if actual["estado"] == "cancelada":
        raise reglas.ErrorValidacion(reglas.RESERVA_YA_CANCELADA, "La reserva ya estaba cancelada", "id")
    if actual["fin"] < ahora_sede().strftime(FORMATO_FECHA):
        raise reglas.ErrorValidacion(reglas.RESERVA_VENCIDA, "La reserva ya terminó y no se puede cancelar", "id")
    con.execute("UPDATE reserva SET estado = 'cancelada' WHERE id = ?", (reserva_id,))
    con.commit()
    return obtener_reserva(con, reserva_id)


def listar_todas_reservas_activas(con):
    ahora_s = ahora_sede().strftime(FORMATO_FECHA)
    filas = con.execute(
        "SELECT r.id, r.codigo_zona, COALESCE(u.nombre, r.codigo_zona) AS zona_nombre, "
        "COALESCE(u.sector, 'Sin sector') AS sector, "
        "r.identificacion, COALESCE(p.nombre, '') AS nombre, COALESCE(p.tipo_vehiculo, '') AS tipo_vehiculo, "
        "r.inicio, r.fin, r.estado, r.creada_en "
        "FROM reserva r "
        "LEFT JOIN zona_ubicacion u ON u.codigo_zona = r.codigo_zona "
        "LEFT JOIN usuario p ON p.identificacion = r.identificacion "
        "WHERE r.estado = 'activa' AND r.fin > ? "
        "ORDER BY r.inicio ASC, r.id ASC",
        (ahora_s,)
    ).fetchall()
    return [dict(f) for f in filas]


def ampliar_reserva(con, reserva_id, minutos=30):
    if not isinstance(minutos, int) or minutos <= 0:
        raise reglas.ErrorValidacion(reglas.CAMPO_INVALIDO, "minutos debe ser un entero positivo", "minutos")

    actual = obtener_reserva(con, reserva_id)  # lanza RESERVA_NO_ENCONTRADA
    if actual["estado"] == "cancelada":
        raise reglas.ErrorValidacion(reglas.RESERVA_YA_CANCELADA, "La reserva ya estaba cancelada y no se puede ampliar", "id")

    ahora = ahora_sede()
    ahora_s = ahora.strftime(FORMATO_FECHA)
    if actual["fin"] < ahora_s:
        raise reglas.ErrorValidacion(reglas.RESERVA_VENCIDA, "La reserva ya terminó y no se puede ampliar", "id")

    fin_actual = datetime.strptime(actual["fin"], FORMATO_FECHA)
    inicio_actual = datetime.strptime(actual["inicio"], FORMATO_FECHA)
    nuevo_fin = fin_actual + timedelta(minutes=minutos)

    zona = detalle_zona(con, actual["codigo_zona"])

    if nuevo_fin.date() != inicio_actual.date() or nuevo_fin.strftime("%H:%M") > zona["hora_cierre"]:
        raise reglas.ErrorValidacion(
            reglas.FUERA_DE_HORARIO,
            f"La ampliación supera la hora de cierre de '{zona['nombre']}' ({zona['hora_cierre']}) o cruza de día",
            "fin",
        )

    duracion_horas = (nuevo_fin - inicio_actual).total_seconds() / 3600
    if duracion_horas > zona["max_horas_reserva"]:
        raise reglas.ErrorValidacion(
            reglas.DURACION_EXCEDIDA,
            f"La duración total ({duracion_horas:g} h) superaría el máximo permitido en esta zona ({zona['max_horas_reserva']} h)",
            "fin",
        )

    nuevo_fin_s = nuevo_fin.strftime(FORMATO_FECHA)
    con.isolation_level = None
    con.execute("BEGIN IMMEDIATE")
    try:
        solapadas = con.execute(
            "SELECT COUNT(*) FROM reserva WHERE codigo_zona = ? AND estado = 'activa' AND id != ? "
            "AND inicio < ? AND fin > ?",
            (actual["codigo_zona"], reserva_id, nuevo_fin_s, actual["inicio"]),
        ).fetchone()[0]

        if zona["capacidad"] - solapadas <= 0:
            raise reglas.ErrorValidacion(
                reglas.SIN_CUPOS_RESERVA,
                f"No hay cupos disponibles en '{zona['nombre']}' para ampliar el tiempo en ese horario",
                "fin",
            )

        con.execute("UPDATE reserva SET fin = ? WHERE id = ?", (nuevo_fin_s, reserva_id))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.isolation_level = ""

    return obtener_reserva(con, reserva_id)


# ==========================================================================
# Claves de las personas (guardadas con hash, nunca en texto plano)
# ==========================================================================
CLAVE_MINIMA = 8


def establecer_clave(con, identificacion, clave):
    ident = str(identificacion or "").strip()
    if not isinstance(clave, str) or len(clave) < CLAVE_MINIMA:
        raise reglas.ErrorValidacion(reglas.CLAVE_DEBIL,
                                     f"La clave debe tener al menos {CLAVE_MINIMA} caracteres", "clave")
    if con.execute("SELECT 1 FROM usuario WHERE identificacion = ?", (ident,)).fetchone() is None:
        raise reglas.ErrorValidacion(reglas.USUARIO_NO_ENCONTRADO,
                                     "Esa identificación no tiene reservas registradas", "identificacion")
    con.execute("UPDATE usuario SET clave_hash = ? WHERE identificacion = ?",
                (seguridad.hash_clave(clave), ident))
    con.commit()
    return {"identificacion": ident, "clave_guardada": True}


def verificar_clave(con, identificacion, clave):
    ident = str(identificacion or "").strip()
    fila = con.execute("SELECT clave_hash FROM usuario WHERE identificacion = ?", (ident,)).fetchone()
    if fila is None:
        raise reglas.ErrorValidacion(reglas.USUARIO_NO_ENCONTRADO,
                                     "Esa identificación no tiene reservas registradas", "identificacion")
    if not fila["clave_hash"] or not seguridad.verificar_clave(str(clave or ""), fila["clave_hash"]):
        raise reglas.ErrorValidacion(reglas.CLAVE_INCORRECTA, "La clave no es correcta", "clave")
    return {"identificacion": ident, "valida": True}
