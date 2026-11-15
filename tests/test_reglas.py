import pytest

from app import reglas

CAP = 577


def test_lectura_valida_se_normaliza():
    r = reglas.validar_lectura(" BHMBCCMKT01 ", "2016-10-04 07:59:42", "61", CAP)
    assert r == {"codigo_zona": "BHMBCCMKT01", "fecha_hora": "2016-10-04 07:59:42", "ocupacion": 61}


@pytest.mark.parametrize("codigo_zona, fecha, ocupacion, capacidad, esperado", [
    ("", "2016-10-04 07:59:42", 5, CAP, reglas.CAMPO_INCOMPLETO),
    ("MKT01", "", 5, CAP, reglas.CAMPO_INCOMPLETO),
    ("MKT01", "2016-10-04 07:59:42", None, CAP, reglas.CAMPO_INCOMPLETO),
    ("MKT01", "2016-13-45 25:00:00", 5, CAP, reglas.FECHA_INVALIDA),
    ("MKT01", "2016-10-04 07:59:42", "abc", CAP, reglas.CAMPO_INVALIDO),
    ("MKT01", "2016-10-04 07:59:42", "12.5", CAP, reglas.CAMPO_INVALIDO),
    ("MKT01", "2016-10-04 07:59:42", "-5", CAP, reglas.OCUPACION_NEGATIVA),
    ("MKT01", "2016-10-04 07:59:42", 5, None, reglas.ZONA_INEXISTENTE),
    ("MKT01", "2016-10-04 07:59:42", 600, CAP, reglas.OCUPACION_SUPERA_CAPACIDAD),
])
def test_cada_regla_tiene_su_codigo(codigo_zona, fecha, ocupacion, capacidad, esperado):
    with pytest.raises(reglas.ErrorValidacion) as e:
        reglas.validar_lectura(codigo_zona, fecha, ocupacion, capacidad)
    assert e.value.codigo == esperado
