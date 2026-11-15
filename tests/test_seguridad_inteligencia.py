"""Pruebas de seguridad (contraseñas, texto seguro) e inteligencia (alerta y predicción).

Usan una base temporal: no modifican salidas/parqueadero.db.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient  # noqa

from app import db, main, seguridad


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    ruta = str(tmp_path / "seg.db")
    monkeypatch.setattr(db, "DB_PATH", ruta)
    db.asegurar_esquema(ruta)
    con = db.conectar(ruta)
    con.executescript("""
        INSERT INTO zona VALUES ('CARRO01', 100);
        INSERT INTO zona VALUES ('MKT01', 100);
        INSERT INTO restriccion_zona (codigo_zona, tipos_permitidos, hora_apertura, hora_cierre,
            max_horas_reserva, max_reservas_activas_usuario, nota)
            VALUES ('CARRO01', 'carro,moto', '00:00', '23:59', 8, 5, '');
    """)
    # Historial: todos los lunes a las 10:00 la zona MKT01 estuvo llena al 80 % y 60 %.
    con.executescript("""
        INSERT INTO lectura_ocupacion (codigo_zona, fecha_hora, ocupacion)
            VALUES ('MKT01', '2016-12-05 10:00:00', 80);
        INSERT INTO lectura_ocupacion (codigo_zona, fecha_hora, ocupacion)
            VALUES ('MKT01', '2016-12-12 10:00:00', 60);
        INSERT INTO lectura_ocupacion (codigo_zona, fecha_hora, ocupacion)
            VALUES ('CARRO01', '2016-12-12 10:00:00', 95);
    """)
    con.commit()
    con.close()
    with TestClient(main.app) as c:
        yield c


# ---------- contraseñas ----------------------------------------------------
def test_clave_se_guarda_con_hash_no_en_texto_plano(cliente, tmp_path):
    cliente.post("/reservas", json={"identificacion": "1001", "nombre": "Ana", "tipo_vehiculo": "carro",
                                    "codigo_zona": "CARRO01", "inicio": "2036-06-10 08:00:00",
                                    "fin": "2036-06-10 09:00:00"})
    r = cliente.post("/usuarios/1001/clave", json={"clave": "clave-secreta-123"})
    assert r.status_code == 200
    assert "clave" not in r.json() or r.json().get("clave") is None
    con = sqlite3.connect(db.DB_PATH)
    guardado = con.execute("SELECT clave_hash FROM usuario WHERE identificacion='1001'").fetchone()[0]
    con.close()
    assert guardado.startswith("pbkdf2_sha256$")
    assert "clave-secreta-123" not in guardado


def test_verificar_clave_correcta_e_incorrecta(cliente):
    cliente.post("/reservas", json={"identificacion": "1002", "nombre": "Luis", "tipo_vehiculo": "moto",
                                    "codigo_zona": "CARRO01", "inicio": "2036-06-10 08:00:00",
                                    "fin": "2036-06-10 09:00:00"})
    cliente.post("/usuarios/1002/clave", json={"clave": "clave-segura-2026"})
    assert cliente.post("/usuarios/1002/verificar-clave", json={"clave": "clave-segura-2026"}).status_code == 200
    r = cliente.post("/usuarios/1002/verificar-clave", json={"clave": "otra-clave-mala"})
    assert r.status_code == 401
    assert r.json()["error"]["codigo"] == "CLAVE_INCORRECTA"


def test_clave_corta_se_rechaza(cliente):
    cliente.post("/reservas", json={"identificacion": "1003", "nombre": "Eva", "tipo_vehiculo": "carro",
                                    "codigo_zona": "CARRO01", "inicio": "2036-06-10 08:00:00",
                                    "fin": "2036-06-10 09:00:00"})
    r = cliente.post("/usuarios/1003/clave", json={"clave": "corta"})
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "CLAVE_DEBIL"


def test_clave_de_persona_inexistente(cliente):
    r = cliente.post("/usuarios/9999/clave", json={"clave": "clave-segura-2026"})
    assert r.status_code == 404
    assert r.json()["error"]["codigo"] == "USUARIO_NO_ENCONTRADO"


def test_hash_no_es_reversible_y_cada_hash_tiene_sal_distinta():
    a = seguridad.hash_clave("mismaclave1")
    b = seguridad.hash_clave("mismaclave1")
    assert a != b
    assert seguridad.verificar_clave("mismaclave1", a)
    assert not seguridad.verificar_clave("mismaclave2", a)
    assert not seguridad.verificar_clave("mismaclave1", "texto-plano")


# ---------- texto seguro en formularios -------------------------------------
@pytest.mark.parametrize("nombre_malicioso", [
    "<script>alert('x')</script>",
    "<img src=x onerror=alert(1)>",
    "Ana <b>Pérez</b>",
    "javascript:alert(1)",
])
def test_nombre_con_codigo_se_rechaza(cliente, nombre_malicioso):
    r = cliente.post("/reservas", json={"identificacion": "2001", "nombre": nombre_malicioso,
                                        "tipo_vehiculo": "carro", "codigo_zona": "CARRO01",
                                        "inicio": "2036-06-10 08:00:00", "fin": "2036-06-10 09:00:00"})
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "TEXTO_PELIGROSO"


def test_placa_con_codigo_se_rechaza(cliente):
    r = cliente.post("/reservas", json={"identificacion": "2002", "nombre": "Ana", "placa": "<svg onload=x>",
                                        "tipo_vehiculo": "carro", "codigo_zona": "CARRO01",
                                        "inicio": "2036-06-10 08:00:00", "fin": "2036-06-10 09:00:00"})
    assert r.json()["error"]["codigo"] == "TEXTO_PELIGROSO"


def test_nombre_normal_con_tildes_y_apostrofe_se_acepta(cliente):
    r = cliente.post("/reservas", json={"identificacion": "2003", "nombre": "María José O'Neil",
                                        "tipo_vehiculo": "carro", "codigo_zona": "CARRO01",
                                        "inicio": "2036-06-10 08:00:00", "fin": "2036-06-10 09:00:00"})
    assert r.status_code == 201


# ---------- inteligencia ---------------------------------------------------
def test_alerta_critica_si_zona_casi_llena(cliente):
    r = cliente.get("/zonas/CARRO01/alerta")
    assert r.status_code == 200
    assert r.json()["nivel"] == "critica"


def test_alerta_normal_si_hay_cupos(cliente):
    r = cliente.get("/zonas/MKT01/alerta")
    assert r.json()["nivel"] == "normal"               # última lectura de MKT01: 60 %


def test_alerta_zona_sin_lecturas_da_404(cliente):
    r = cliente.get("/zonas/NADA/alerta")
    assert r.status_code == 404


def test_prediccion_usa_promedio_del_mismo_dia_y_hora(cliente):
    # 2036-06-10 es sábado (%w = 6). El historial de MKT01 es lunes 10:00, así que no hay datos de sábado.
    r = cliente.get("/zonas/MKT01/prediccion", params={"fecha_hora": "2016-12-19 10:00:00"})  # lunes
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["dia_semana"] == "lunes"
    assert cuerpo["ocupacion_estimada"] == 70          # promedio de 80 y 60
    assert cuerpo["muestras_historicas"] == 2
    assert cuerpo["porcentaje_estimado"] == 70.0


def test_prediccion_sin_historial_responde_404(cliente):
    r = cliente.get("/zonas/MKT01/prediccion", params={"fecha_hora": "2016-12-20 15:00:00"})  # martes, sin datos
    assert r.status_code == 404
    assert r.json()["error"]["codigo"] == "SIN_HISTORIAL"


def test_prediccion_fecha_invalida(cliente):
    r = cliente.get("/zonas/MKT01/prediccion", params={"fecha_hora": "no-es-fecha"})
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "FECHA_INVALIDA"


def test_migracion_agrega_columna_clave_a_base_antigua(tmp_path):
    ruta = str(tmp_path / "vieja.db")
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE usuario (identificacion TEXT PRIMARY KEY, nombre TEXT NOT NULL, "
                "tipo_vehiculo TEXT NOT NULL, placa TEXT NOT NULL DEFAULT '')")
    con.commit()
    con.close()
    db.asegurar_esquema(ruta)
    con = sqlite3.connect(ruta)
    columnas = {f[1] for f in con.execute("PRAGMA table_info(usuario)").fetchall()}
    con.close()
    assert "clave_hash" in columnas
