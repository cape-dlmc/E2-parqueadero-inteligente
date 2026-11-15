"""Genera los catálogos del sistema a partir de los datos originales.

Salidas en 01_dataset/:
  catalogo_zonas.csv          codigo_zona, capacidad      (regla de E1: capacidad = moda)
  sedes.csv                   sede única: Montería
  ubicacion_zonas.csv         en qué sector y posición del esquema queda cada zona
  restricciones_zonas.csv     qué se puede reservar en cada zona y bajo qué condiciones

Uso: python -m pipeline.generar_catalogo
Los archivos de ubicación y restricciones son datos editables: puedes cambiarlos y volver a cargar.
"""
import csv
import pathlib

import pandas as pd

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DATOS = RAIZ / "01_dataset"
ORIGEN = DATOS / "datos_originales.csv"

# Sede única del proyecto. Coordenadas aproximadas de Montería (Córdoba, Colombia).
SEDE = {"id": 1, "nombre": "Sede Montería · Campus principal", "ciudad": "Montería",
        "departamento": "Córdoba", "latitud": 8.7479, "longitud": -75.8814}

# Sectores del esquema. Cada sector ocupa una fila de 6 zonas en el plano de la sede.
SECTORES = ["Norte", "Oriente", "Centro", "Occidente", "Sur"]
ZONAS_POR_SECTOR = 6
RESTRICCION_CENTRO = {"tipos": "carro", "apertura": "07:00", "cierre": "20:00",
                      "max_horas": 4, "max_reservas": 1,
                      "nota": "Zona central: solo carros y horario reducido"}
RESTRICCION_GENERAL = {"tipos": "carro,moto", "apertura": "06:00", "cierre": "22:00",
                       "max_horas": 8, "max_reservas": 2, "nota": ""}
CAPACIDAD_MINIMA_RESERVABLE = 300


def _escribir(ruta, columnas, filas):
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)


def generar():
    df = pd.read_csv(ORIGEN)
    catalogo = (df.groupby("SystemCodeNumber")["Capacity"]
                  .agg(lambda s: int(s.mode().iloc[0]))
                  .reset_index())
    catalogo.columns = ["codigo_zona", "capacidad"]
    catalogo.to_csv(DATOS / "catalogo_zonas.csv", index=False)

    _escribir(DATOS / "sedes.csv", list(SEDE.keys()), [SEDE])

    ubicaciones, restricciones = [], []
    for i, fila in enumerate(catalogo.itertuples(index=False)):
        sector = SECTORES[i // ZONAS_POR_SECTOR % len(SECTORES)]
        columna = i % ZONAS_POR_SECTOR
        fila_idx = i // ZONAS_POR_SECTOR
        ubicaciones.append({
            "codigo_zona": fila.codigo_zona, "sede_id": SEDE["id"],
            "nombre": f"{sector} · Bloque {columna + 1}", "sector": sector,
            "x": 8 + columna * 16, "y": 10 + fila_idx * 18,
        })
        r = RESTRICCION_CENTRO if sector == "Centro" else RESTRICCION_GENERAL
        pequena = fila.capacidad < CAPACIDAD_MINIMA_RESERVABLE
        restricciones.append({
            "codigo_zona": fila.codigo_zona,
            "reservable": 0 if pequena else 1,
            "tipos_permitidos": r["tipos"],
            "hora_apertura": r["apertura"],
            "hora_cierre": r["cierre"],
            "max_horas_reserva": r["max_horas"],
            "max_reservas_activas_usuario": r["max_reservas"],
            "nota": "Zona pequeña de rotación" if pequena else r["nota"],
        })

    _escribir(DATOS / "ubicacion_zonas.csv",
              ["codigo_zona", "sede_id", "nombre", "sector", "x", "y"], ubicaciones)
    _escribir(DATOS / "restricciones_zonas.csv",
              ["codigo_zona", "reservable", "tipos_permitidos", "hora_apertura", "hora_cierre",
               "max_horas_reserva", "max_reservas_activas_usuario", "nota"], restricciones)
    print(f"Catálogo escrito con {len(catalogo)} zonas en Montería "
          f"(catalogo_zonas, sedes, ubicacion_zonas, restricciones_zonas)")


if __name__ == "__main__":
    generar()
