from pipeline import etl

CATALOGO = "codigo_zona,capacidad\nMKT01,100\nPST01,50\n"
ORIGEN = (
    "SystemCodeNumber,Capacity,Occupancy,LastUpdated\n"
    "MKT01,100,10,2016-12-01 10:00:00\n"      # válida
    "MKT01,100,10,2016-12-01 10:00:00\n"      # duplicado exacto
    "MKT01,100,20,2016-12-01 11:00:00\n"      # válida
    "MKT01,100,30,2016-12-01 11:00:00\n"      # conflicto dentro del archivo -> se rechazan las dos
    "MKT01,100,-4,2016-12-01 12:00:00\n"      # negativa
    "NOEXISTE,50,5,2016-12-01 12:00:00\n"     # zona inexistente
)


def test_reconciliacion_y_no_duplicar(tmp_path):
    cat = tmp_path / "cat.csv"; cat.write_text(CATALOGO, encoding="utf-8")
    ori = tmp_path / "origen.csv"; ori.write_text(ORIGEN, encoding="utf-8")
    db_path = str(tmp_path / "t.db"); salidas = tmp_path / "s"

    r1 = etl.ejecutar(ori, db_path, cat, salidas, reiniciar=True)
    assert r1["aceptadas_nuevas"] == 1  # solo la de 10:00: las dos de 11:00 se contradicen
    assert r1["duplicados_exactos_descartados"] == 1
    assert r1["rechazadas"] == 4
    assert r1["reconciliacion_filas_ok"] is True

    r2 = etl.ejecutar(ori, db_path, cat, salidas)  # segunda ejecución
    assert r2["aceptadas_nuevas"] == 0
    assert r2["ya_existian_identicas"] == 1
    assert r2["lecturas_en_bd_antes"] == r2["lecturas_en_bd_despues"] == 1
    assert r2["consistencia_bd_ok"] is True
