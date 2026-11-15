"""Pruebas de reservas y restricciones por zona (API y base de datos).

Usan una base temporal: no modifican salidas/parqueadero.db.
Las fechas son de 2036 para que siempre queden en el futuro.
"""
import pytest
from fastapi.testclient import TestClient  # noqa

from app import db, main


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    ruta = str(tmp_path / "reservas.db")
    monkeypatch.setattr(db, "DB_PATH", ruta)
    db.asegurar_esquema(ruta)
    con = db.conectar(ruta)
    con.executescript("""
        INSERT INTO zona VALUES ('MKT01', 100);
        INSERT INTO zona VALUES ('CARRO01', 100);
        INSERT INTO zona VALUES ('NOR01', 100);
        INSERT INTO zona VALUES ('SMALL', 1);
        INSERT INTO restriccion_zona (codigo_zona, tipos_permitidos, hora_apertura, hora_cierre,
            max_horas_reserva, max_reservas_activas_usuario, nota)
            VALUES ('CARRO01', 'carro', '07:00', '20:00', 4, 1, 'Zona central');
        INSERT INTO restriccion_zona (codigo_zona, reservable, nota)
            VALUES ('NOR01', 0, 'Zona de rotación');
    """)
    con.commit()
    con.close()
    with TestClient(main.app) as c:
        yield c


def cuerpo(**cambios):
    base = {"identificacion": "1001", "nombre": "Ana Pérez", "tipo_vehiculo": "carro",
            "codigo_zona": "MKT01", "inicio": "2036-06-10 08:00:00", "fin": "2036-06-10 10:00:00"}
    base.update(cambios)
    return base


def test_crear_reserva_devuelve_201_y_la_guarda(cliente):
    r = cliente.post("/reservas", json=cuerpo())
    assert r.status_code == 201
    datos = r.json()
    assert datos["estado"] == "activa"
    assert datos["codigo_zona"] == "MKT01"
    assert datos["identificacion"] == "1001"


def test_la_reserva_queda_en_la_base_de_datos(cliente, monkeypatch):
    cliente.post("/reservas", json=cuerpo(placa="abc123"))
    con = db.conectar(db.DB_PATH)
    fila = con.execute("SELECT codigo_zona, estado FROM reserva").fetchone()
    usuario = con.execute("SELECT placa FROM usuario WHERE identificacion = '1001'").fetchone()
    con.close()
    assert fila["estado"] == "activa"
    assert usuario["placa"] == "ABC123"


def test_la_misma_persona_no_puede_tener_dos_reservas_en_el_mismo_horario(cliente):
    cliente.post("/reservas", json=cuerpo())
    r = cliente.post("/reservas", json=cuerpo(inicio="2036-06-10 09:00:00", fin="2036-06-10 11:00:00"))
    assert r.status_code == 409
    assert r.json()["error"]["codigo"] == "USUARIO_CON_RESERVA_SOLAPADA"


def test_limite_de_reservas_activas_por_persona(cliente):
    # MKT01 permite 2 reservas activas por persona.
    assert cliente.post("/reservas", json=cuerpo(inicio="2036-06-10 08:00:00", fin="2036-06-10 09:00:00")).status_code == 201
    assert cliente.post("/reservas", json=cuerpo(inicio="2036-06-11 08:00:00", fin="2036-06-11 09:00:00")).status_code == 201
    r = cliente.post("/reservas", json=cuerpo(inicio="2036-06-12 08:00:00", fin="2036-06-12 09:00:00"))
    assert r.status_code == 409
    assert r.json()["error"]["codigo"] == "LIMITE_RESERVAS_USUARIO"


def test_fuera_de_horario_es_422(cliente):
    # CARRO01 abre de 07:00 a 20:00
    r = cliente.post("/reservas", json=cuerpo(codigo_zona="CARRO01", tipo_vehiculo="carro",
                                              inicio="2036-06-10 19:00:00", fin="2036-06-10 21:00:00"))
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "FUERA_DE_HORARIO"


def test_duracion_mayor_al_maximo_es_422(cliente):
    # CARRO01 permite máximo 4 horas
    r = cliente.post("/reservas", json=cuerpo(codigo_zona="CARRO01", tipo_vehiculo="carro",
                                              inicio="2036-06-10 08:00:00", fin="2036-06-10 13:00:00"))
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "DURACION_EXCEDIDA"


def test_tipo_de_vehiculo_no_permitido_es_422(cliente):
    r = cliente.post("/reservas", json=cuerpo(codigo_zona="CARRO01", tipo_vehiculo="moto"))
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "TIPO_NO_PERMITIDO"


def test_zona_no_reservable_es_422(cliente):
    r = cliente.post("/reservas", json=cuerpo(codigo_zona="NOR01"))
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "ZONA_NO_RESERVABLE"


def test_zona_inexistente_es_404(cliente):
    r = cliente.post("/reservas", json=cuerpo(codigo_zona="NOEXISTE"))
    assert r.status_code == 404
    assert r.json()["error"]["codigo"] == "ZONA_INEXISTENTE"


def test_reserva_en_el_pasado_es_422(cliente):
    r = cliente.post("/reservas", json=cuerpo(inicio="2020-01-01 08:00:00", fin="2020-01-01 09:00:00"))
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "RESERVA_EN_PASADO"


def test_fin_antes_que_inicio_es_422(cliente):
    r = cliente.post("/reservas", json=cuerpo(inicio="2036-06-10 10:00:00", fin="2036-06-10 08:00:00"))
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "RANGO_INVALIDO"


def test_campo_faltante_es_422(cliente):
    r = cliente.post("/reservas", json=cuerpo(nombre=""))
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "CAMPO_INCOMPLETO"


def test_sin_cupos_es_409(cliente):
    # SMALL tiene capacidad 1: la segunda persona en el mismo horario no cabe.
    assert cliente.post("/reservas", json=cuerpo(codigo_zona="SMALL")).status_code == 201
    r = cliente.post("/reservas", json=cuerpo(codigo_zona="SMALL", identificacion="2002", nombre="Luis"))
    assert r.status_code == 409
    assert r.json()["error"]["codigo"] == "SIN_CUPOS_RESERVA"


def test_cancelar_libera_el_cupo(cliente):
    cliente.post("/reservas", json=cuerpo(codigo_zona="SMALL"))
    id_reserva = cliente.get("/reservas", params={"identificacion": "1001"}).json()[0]["id"]
    assert cliente.post(f"/reservas/{id_reserva}/cancelar").json()["estado"] == "cancelada"
    r = cliente.post("/reservas", json=cuerpo(codigo_zona="SMALL", identificacion="2002", nombre="Luis"))
    assert r.status_code == 201


def test_cancelar_dos_veces_es_409(cliente):
    cliente.post("/reservas", json=cuerpo())
    id_reserva = cliente.get("/reservas", params={"identificacion": "1001"}).json()[0]["id"]
    cliente.post(f"/reservas/{id_reserva}/cancelar")
    r = cliente.post(f"/reservas/{id_reserva}/cancelar")
    assert r.status_code == 409
    assert r.json()["error"]["codigo"] == "RESERVA_YA_CANCELADA"


def test_cancelar_inexistente_es_404(cliente):
    r = cliente.post("/reservas/9999/cancelar")
    assert r.status_code == 404
    assert r.json()["error"]["codigo"] == "RESERVA_NO_ENCONTRADA"


def test_disponibilidad_descuenta_reservas_que_se_cruzan(cliente):
    cliente.post("/reservas", json=cuerpo(codigo_zona="SMALL"))
    r = cliente.get("/zonas/SMALL/disponibilidad",
                    params={"inicio": "2036-06-10 09:00:00", "fin": "2036-06-10 09:30:00"}).json()
    assert r["reservas_que_se_cruzan"] == 1
    assert r["cupos_para_reservar"] == 0
    otro_horario = cliente.get("/zonas/SMALL/disponibilidad",
                               params={"inicio": "2036-06-11 09:00:00", "fin": "2036-06-11 10:00:00"}).json()
    assert otro_horario["cupos_para_reservar"] == 1


def test_zonas_exponen_restricciones(cliente):
    zonas = {z["codigo_zona"]: z for z in cliente.get("/zonas").json()}
    assert zonas["CARRO01"]["tipos_permitidos"] == ["carro"]
    assert zonas["CARRO01"]["max_horas_reserva"] == 4
    assert zonas["NOR01"]["reservable"] is False
    assert zonas["MKT01"]["reservable"] is True


def test_ampliar_reserva_extiende_el_fin(cliente):
    creada = cliente.post("/reservas", json=cuerpo(codigo_zona="CARRO01", inicio="2036-06-10 08:00:00", fin="2036-06-10 09:00:00")).json()
    r = cliente.post(f"/reservas/{creada['id']}/ampliar", json={"minutos": 60})
    assert r.status_code == 200
    ampliada = r.json()
    assert ampliada["fin"] == "2036-06-10 10:00:00"


def test_ampliar_reserva_excediendo_duracion_es_422(cliente):
    # CARRO01 maximo 4 horas
    creada = cliente.post("/reservas", json=cuerpo(codigo_zona="CARRO01", inicio="2036-06-10 08:00:00", fin="2036-06-10 11:30:00")).json()
    r = cliente.post(f"/reservas/{creada['id']}/ampliar", json={"minutos": 60})
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "DURACION_EXCEDIDA"


def test_listar_todas_reservas_activas(cliente):
    cliente.post("/reservas", json=cuerpo(identificacion="U1", inicio="2036-06-10 08:00:00", fin="2036-06-10 09:00:00"))
    cliente.post("/reservas", json=cuerpo(identificacion="U2", inicio="2036-06-10 10:00:00", fin="2036-06-10 11:00:00"))
    r = cliente.get("/reservas/activas")
    assert r.status_code == 200
    datos = r.json()
    assert len(datos) >= 2

