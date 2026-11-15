"""Pipeline reproducible de E2.

Pasos:
 1) cargar el catálogo de zonas
 2) leer el archivo de origen
 3) validar cada fila con app/reglas.py (las mismas reglas que la API)
 4) resolver duplicados dentro del archivo (idénticos se descartan; contradictorios se rechazan)
 5) cargar contra la BD sin duplicar (misma lectura = ya existía; valor distinto = conflicto)
 6) reconciliar: filas leídas = nuevas + ya existían + duplicados descartados + rechazadas
 7) exportar el producto final (última ocupación de cada zona)

Todo ocurre en UNA transacción: si algo falla, no queda nada a medias.

Uso:
  python -m pipeline.etl --reiniciar                  # reconstruye la BD desde los datos originales
  python -m pipeline.etl                              # segunda ejecución: no duplica nada
  python -m pipeline.etl --origen 01_dataset/anomalias_prueba.csv
"""
import argparse
import csv
import json
import os
import pathlib
import sys
from collections import Counter, defaultdict

from app import db, reglas
from app.servicio import SQL_ULTIMA_OCUPACION

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CATALOGO_DEFAULT = RAIZ / "01_dataset" / "catalogo_zonas.csv"
ORIGEN_DEFAULT = RAIZ / "01_dataset" / "datos_originales.csv"
SALIDAS_DEFAULT = RAIZ / "salidas"
COLUMNAS = ["SystemCodeNumber", "Capacity", "Occupancy", "LastUpdated"]


def cargar_catalogo(con, ruta):
    with open(ruta, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    catalogo = {}
    for r in filas:
        codigo = r["codigo_zona"].strip()
        capacidad = int(r["capacidad"])
        con.execute(
            "INSERT INTO zona (codigo_zona, capacidad) VALUES (?, ?) "
            "ON CONFLICT(codigo_zona) DO UPDATE SET capacidad = excluded.capacidad",
            (codigo, capacidad))
        catalogo[codigo] = capacidad
    return catalogo


def cargar_complementos(con, carpeta):
    """Carga sede, ubicación y restricciones de zona si los archivos existen en la carpeta."""
    carpeta = pathlib.Path(carpeta)
    cargados = {}

    ruta = carpeta / "sedes.csv"
    if ruta.exists():
        with open(ruta, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                con.execute(
                    "INSERT INTO sede (id, nombre, ciudad, departamento, latitud, longitud) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET nombre = excluded.nombre, ciudad = excluded.ciudad, "
                    "departamento = excluded.departamento, latitud = excluded.latitud, longitud = excluded.longitud",
                    (int(r["id"]), r["nombre"], r["ciudad"], r["departamento"],
                     float(r["latitud"]), float(r["longitud"])))
        cargados["sedes"] = True

    ruta = carpeta / "ubicacion_zonas.csv"
    if ruta.exists():
        with open(ruta, newline="", encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        for r in filas:
            con.execute(
                "INSERT INTO zona_ubicacion (codigo_zona, sede_id, nombre, sector, x, y) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(codigo_zona) DO UPDATE SET sede_id = excluded.sede_id, nombre = excluded.nombre, "
                "sector = excluded.sector, x = excluded.x, y = excluded.y",
                (r["codigo_zona"], int(r["sede_id"]), r["nombre"], r["sector"], int(r["x"]), int(r["y"])))
        cargados["ubicaciones"] = len(filas)

    ruta = carpeta / "restricciones_zonas.csv"
    if ruta.exists():
        with open(ruta, newline="", encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        for r in filas:
            con.execute(
                "INSERT INTO restriccion_zona (codigo_zona, reservable, tipos_permitidos, hora_apertura, hora_cierre, "
                "max_horas_reserva, max_reservas_activas_usuario, nota) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(codigo_zona) DO UPDATE SET reservable = excluded.reservable, "
                "tipos_permitidos = excluded.tipos_permitidos, hora_apertura = excluded.hora_apertura, "
                "hora_cierre = excluded.hora_cierre, max_horas_reserva = excluded.max_horas_reserva, "
                "max_reservas_activas_usuario = excluded.max_reservas_activas_usuario, nota = excluded.nota",
                (r["codigo_zona"], int(r["reservable"]), r["tipos_permitidos"], r["hora_apertura"],
                 r["hora_cierre"], int(r["max_horas_reserva"]), int(r["max_reservas_activas_usuario"]),
                 r["nota"]))
        cargados["restricciones"] = len(filas)
    return cargados


def leer_origen(ruta):
    with open(ruta, newline="", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        faltan = [c for c in COLUMNAS if c not in (lector.fieldnames or [])]
        if faltan:
            raise SystemExit(f"ERROR: {ruta} no tiene las columnas {faltan}")
        return [(num, fila) for num, fila in enumerate(lector, start=2)]


def ejecutar(origen, db_path, catalogo_path, salidas, reiniciar=False):
    origen = pathlib.Path(origen)
    salidas = pathlib.Path(salidas)
    salidas.mkdir(parents=True, exist_ok=True)
    if reiniciar and os.path.exists(db_path):
        os.remove(db_path)
    db.asegurar_esquema(db_path)
    filas = leer_origen(origen)

    con = db.conectar(db_path)
    con.isolation_level = None  # transacción explícita
    try:
        con.execute("BEGIN")
        catalogo = cargar_catalogo(con, catalogo_path)
        cargar_complementos(con, pathlib.Path(catalogo_path).parent)
        total_antes = con.execute("SELECT COUNT(*) FROM lectura_ocupacion").fetchone()[0]

        rechazadas = []   # (linea, codigo_motivo, mensaje, fila_original)
        validas = []
        capacidad_distinta = 0

        # Paso 3: validación fila a fila con las reglas de la API
        for linea, fila in filas:
            codigo_bruto = (fila.get("SystemCodeNumber") or "").strip()
            try:
                limpia = reglas.validar_lectura(fila.get("SystemCodeNumber"), fila.get("LastUpdated"),
                                                fila.get("Occupancy"), catalogo.get(codigo_bruto))
            except reglas.ErrorValidacion as e:
                rechazadas.append((linea, e.codigo, e.mensaje, fila))
                continue
            # Capacidad reportada distinta del catálogo: advertencia, no rechazo
            try:
                if int(fila.get("Capacity")) != catalogo[limpia["codigo_zona"]]:
                    capacidad_distinta += 1
            except (TypeError, ValueError):
                capacidad_distinta += 1
            validas.append({"linea": linea, "fila": fila, **limpia})

        # Paso 4: duplicados dentro del archivo
        grupos = defaultdict(list)
        for v in validas:
            grupos[(v["codigo_zona"], v["fecha_hora"])].append(v)
        a_cargar, dup_exactos = [], 0
        for grupo in grupos.values():
            if len({g["ocupacion"] for g in grupo}) > 1:
                for g in grupo:
                    rechazadas.append((g["linea"], reglas.LECTURA_CONFLICTIVA,
                                       "Misma zona y hora con ocupaciones distintas en el archivo",
                                       g["fila"]))
            else:
                a_cargar.append(min(grupo, key=lambda g: g["linea"]))
                dup_exactos += len(grupo) - 1
        a_cargar.sort(key=lambda g: g["linea"])

        # Paso 5: carga contra la BD sin duplicar
        nuevas = ya_existian = 0
        for v in a_cargar:
            existente = con.execute(
                "SELECT ocupacion FROM lectura_ocupacion WHERE codigo_zona = ? AND fecha_hora = ?",
                (v["codigo_zona"], v["fecha_hora"])).fetchone()
            if existente is None:
                con.execute(
                    "INSERT INTO lectura_ocupacion (codigo_zona, fecha_hora, ocupacion) VALUES (?, ?, ?)",
                    (v["codigo_zona"], v["fecha_hora"], v["ocupacion"]))
                nuevas += 1
            elif existente[0] == v["ocupacion"]:
                ya_existian += 1
            else:
                rechazadas.append((v["linea"], reglas.LECTURA_CONFLICTIVA,
                                   f"La BD ya tiene ocupacion {existente[0]} para esa zona y hora",
                                   v["fila"]))

        total_despues = con.execute("SELECT COUNT(*) FROM lectura_ocupacion").fetchone()[0]
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()

    # Paso 6: reconciliación
    leidas = len(filas)
    motivos = Counter(m for _, m, _, _ in rechazadas)
    cuadra = leidas == nuevas + ya_existian + dup_exactos + len(rechazadas)
    consistente_bd = total_antes + nuevas == total_despues
    stem = origen.stem

    with open(salidas / f"rechazados_{stem}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["linea_origen", "codigo_motivo", "mensaje", "SystemCodeNumber",
                    "Capacity", "Occupancy", "LastUpdated"])
        for linea, motivo, mensaje, fila in sorted(rechazadas, key=lambda r: r[0]):
            w.writerow([linea, motivo, mensaje, fila.get("SystemCodeNumber"), fila.get("Capacity"),
                        fila.get("Occupancy"), fila.get("LastUpdated")])

    reconciliacion = {
        "archivo_origen": origen.name,
        "filas_leidas": leidas,
        "aceptadas_nuevas": nuevas,
        "ya_existian_identicas": ya_existian,
        "duplicados_exactos_descartados": dup_exactos,
        "rechazadas": len(rechazadas),
        "rechazadas_por_motivo": dict(sorted(motivos.items())),
        "reconciliacion_filas_ok": cuadra,
        "lecturas_en_bd_antes": total_antes,
        "lecturas_en_bd_despues": total_despues,
        "consistencia_bd_ok": consistente_bd,
        "capacidad_reportada_distinta_del_catalogo": capacidad_distinta,
    }
    with open(salidas / f"reconciliacion_{stem}.json", "w", encoding="utf-8") as f:
        json.dump(reconciliacion, f, ensure_ascii=False, indent=2)

    # Paso 7: producto final (última ocupación de cada zona)
    con2 = db.conectar(db_path)
    try:
        producto = [dict(r) for r in con2.execute(SQL_ULTIMA_OCUPACION).fetchall()]
    finally:
        con2.close()
    with open(salidas / "producto_final_ultima_ocupacion.csv", "w", newline="", encoding="utf-8") as f:
        if producto:
            w = csv.DictWriter(f, fieldnames=list(producto[0].keys()))
            w.writeheader()
            w.writerows(producto)

    return reconciliacion


def main():
    p = argparse.ArgumentParser(description="Pipeline reproducible E2 · Parqueadero")
    p.add_argument("--origen", default=str(ORIGEN_DEFAULT))
    p.add_argument("--catalogo", default=str(CATALOGO_DEFAULT))
    p.add_argument("--db", default=db.DB_PATH)
    p.add_argument("--salidas", default=str(SALIDAS_DEFAULT))
    p.add_argument("--reiniciar", action="store_true", help="borra la BD y la reconstruye")
    a = p.parse_args()
    rec = ejecutar(a.origen, a.db, a.catalogo, a.salidas, a.reiniciar)
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    sys.exit(0 if rec["reconciliacion_filas_ok"] and rec["consistencia_bd_ok"] else 1)


if __name__ == "__main__":
    main()
