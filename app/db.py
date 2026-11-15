"""Conexión y esquema de la base de datos SQLite."""
import os
import pathlib
import sqlite3

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("PARQUEADERO_DB", str(RAIZ / "salidas" / "parqueadero.db"))
SCHEMA_PATH = RAIZ / "schema.sql"


def conectar(path=None):
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def asegurar_esquema(path=None):
    ruta = path or DB_PATH
    pathlib.Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    try:
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        columnas = {f[1] for f in con.execute("PRAGMA table_info(usuario)").fetchall()}
        if columnas and "clave_hash" not in columnas:   # bases creadas antes de v6
            con.execute("ALTER TABLE usuario ADD COLUMN clave_hash TEXT NOT NULL DEFAULT ''")
        con.commit()
    finally:
        con.close()
