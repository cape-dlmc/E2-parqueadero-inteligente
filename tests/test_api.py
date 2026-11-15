import pytest
from fastapi.testclient import TestClient  # noqa

from app import db, main


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    ruta = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", ruta)
    db.asegurar_esquema(ruta)
    con = db.conectar(ruta)
    con.execute("INSERT INTO zona VALUES ('MKT01', 100)")
    con.execute("INSERT INTO zona VALUES ('PST01', 50)")
    con.commit()
    con.close()
    with TestClient(main.app) as c:
        yield c


def test_crear_lectura_devuelve_201(cliente):
    r = cliente.post("/lecturas", json={"codigo_zona": "MKT01", "fecha_hora": "2016-12-01 10:00:00", "ocupacion": 40})
    assert r.status_code == 201
    assert r.json()["estado"] == "creada"


def test_misma_lectura_otra_vez_no_duplica(cliente):
    cuerpo = {"codigo_zona": "MKT01", "fecha_hora": "2016-12-01 10:00:00", "ocupacion": 40}
    cliente.post("/lecturas", json=cuerpo)
    r = cliente.post("/lecturas", json=cuerpo)
    assert r.status_code == 200
    assert r.json()["estado"] == "ya_existia"


def test_misma_hora_con_otro_valor_es_conflicto(cliente):
    cliente.post("/lecturas", json={"codigo_zona": "MKT01", "fecha_hora": "2016-12-01 10:00:00", "ocupacion": 40})
    r = cliente.post("/lecturas", json={"codigo_zona": "MKT01", "fecha_hora": "2016-12-01 10:00:00", "ocupacion": 45})
    assert r.status_code == 409
    assert r.json()["error"]["codigo"] == "LECTURA_CONFLICTIVA"


@pytest.mark.parametrize("cuerpo, status, codigo", [
    ({"codigo_zona": "ZZZ", "fecha_hora": "2016-12-01 10:00:00", "ocupacion": 5}, 404, "ZONA_INEXISTENTE"),
    ({"codigo_zona": "MKT01", "fecha_hora": "2016-12-01 10:00:00", "ocupacion": 500}, 422, "OCUPACION_SUPERA_CAPACIDAD"),
    ({"codigo_zona": "MKT01", "fecha_hora": "2016-12-01 10:00:00", "ocupacion": -3}, 422, "OCUPACION_NEGATIVA"),
    ({"codigo_zona": "MKT01", "fecha_hora": "2016-12-01 10:00:00", "ocupacion": "abc"}, 422, "CAMPO_INVALIDO"),
    ({"codigo_zona": "MKT01", "fecha_hora": "1-dic", "ocupacion": 5}, 422, "FECHA_INVALIDA"),
    ({"codigo_zona": "MKT01", "fecha_hora": "2016-12-01 10:00:00"}, 422, "CAMPO_INCOMPLETO"),
])
def test_errores_distinguibles(cliente, cuerpo, status, codigo):
    r = cliente.post("/lecturas", json=cuerpo)
    assert r.status_code == status
    assert r.json()["error"]["codigo"] == codigo


def test_json_malformado(cliente):
    r = cliente.post("/lecturas", content=b"{no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "JSON_INVALIDO"


def test_ultima_sin_lecturas(cliente):
    r = cliente.get("/zonas/PST01/ultima")
    assert r.status_code == 404
    assert r.json()["error"]["codigo"] == "SIN_LECTURAS"


def test_ultima_y_recomendadas(cliente):
    cliente.post("/lecturas", json={"codigo_zona": "MKT01", "fecha_hora": "2016-12-01 10:00:00", "ocupacion": 80})
    cliente.post("/lecturas", json={"codigo_zona": "PST01", "fecha_hora": "2016-12-01 10:00:00", "ocupacion": 10})
    u = cliente.get("/zonas/MKT01/ultima").json()
    assert u["porcentaje_ocupado"] == 80.0 and u["cupos_libres"] == 20
    rec = cliente.get("/zonas/recomendadas?limite=2").json()
    assert [z["codigo_zona"] for z in rec] == ["PST01", "MKT01"]  # la menos llena primero
