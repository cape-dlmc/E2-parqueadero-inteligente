"""Muestra del Momento 3: recorre los 7 pasos sobre una base temporal.

Uso:  python demostracion_momento3.py
No modifica salidas/parqueadero.db. Imprime cada paso y guarda el resultado en
evidencias/08_momento3.txt (la evidencia de texto que acompaña las capturas).
"""
import json
import pathlib
import tempfile

from fastapi.testclient import TestClient

from app import db, main

RAIZ = pathlib.Path(__file__).resolve().parent
salida = []


def paso(numero, titulo):
    linea = f"\n=== PASO {numero} · {titulo} ==="
    print(linea)
    salida.append(linea)


def mostrar(etiqueta, respuesta):
    texto = f"{etiqueta} -> HTTP {respuesta.status_code}\n{json.dumps(respuesta.json(), ensure_ascii=False, indent=2)}"
    print(texto)
    salida.append(texto)


ruta = str(pathlib.Path(tempfile.mkdtemp()) / "demo_momento3.db")
db.DB_PATH = ruta
db.asegurar_esquema(ruta)
con = db.conectar(ruta)
con.executescript(
    "INSERT INTO zona VALUES ('CARRO01', 100);"
    "INSERT INTO restriccion_zona (codigo_zona, tipos_permitidos, hora_apertura, hora_cierre,"
    " max_horas_reserva, max_reservas_activas_usuario, nota)"
    " VALUES ('CARRO01', 'carro,moto', '00:00', '23:59', 8, 5, '');"
    "INSERT INTO lectura_ocupacion (codigo_zona, fecha_hora, ocupacion) VALUES ('CARRO01','2016-12-05 10:00:00', 95);"
    "INSERT INTO lectura_ocupacion (codigo_zona, fecha_hora, ocupacion) VALUES ('CARRO01','2016-12-12 10:00:00', 91);"
)
con.commit()
con.close()

with TestClient(main.app) as c:
    paso(1, "La idea: zona de carros con cupos y reservas")
    salida.append("Problema: saber dónde parquear sin dar vueltas. Usuario: estudiante o docente de la sede.")

    paso(2, "La app funcionando: recorrido completo")
    mostrar("Crear reserva", c.post("/reservas", json={
        "identificacion": "1001234567", "nombre": "Ana Pérez", "tipo_vehiculo": "carro",
        "placa": "abc123", "codigo_zona": "CARRO01",
        "inicio": "2036-06-10 08:00:00", "fin": "2036-06-10 10:00:00"}))
    mostrar("Ver mis reservas", c.get("/reservas", params={"identificacion": "1001234567"}))

    paso(3, "Datos: no se duplican al repetir la carga")
    lectura = {"codigo_zona": "CARRO01", "fecha_hora": "2016-12-19 09:00:00", "ocupacion": 40}
    mostrar("Primera carga", c.post("/lecturas", json=lectura))
    mostrar("Misma lectura otra vez", c.post("/lecturas", json=lectura))

    paso(4, "Seguridad: código en formulario y contraseña con hash")
    mostrar("Nombre con etiqueta <script>", c.post("/reservas", json={
        "identificacion": "2002", "nombre": "<script>alert(1)</script>", "tipo_vehiculo": "carro",
        "codigo_zona": "CARRO01", "inicio": "2036-06-11 08:00:00", "fin": "2036-06-11 09:00:00"}))
    mostrar("Guardar clave", c.post("/usuarios/1001234567/clave", json={"clave": "clave-segura-2026"}))
    con = db.conectar(ruta)
    guardado = con.execute("SELECT clave_hash FROM usuario WHERE identificacion='1001234567'").fetchone()[0]
    con.close()
    texto = f"Clave en la base de datos (no es legible): {guardado[:40]}..."
    print(texto); salida.append(texto)
    mostrar("Verificar clave correcta", c.post("/usuarios/1001234567/verificar-clave", json={"clave": "clave-segura-2026"}))
    mostrar("Verificar clave incorrecta", c.post("/usuarios/1001234567/verificar-clave", json={"clave": "mala-clave-000"}))

    paso(5, "Inteligencia: alerta por regla y predicción con datos propios")
    mostrar("Alerta de la zona", c.get("/zonas/CARRO01/alerta"))
    mostrar("Predicción para un lunes a las 10:00", c.get("/zonas/CARRO01/prediccion",
                                                       params={"fecha_hora": "2016-12-19 10:00:00"}))

    paso(6, "Dato malo: qué responde la app")
    for nombre, cuerpo in [
        ("Incompleto (sin zona)", {"identificacion": "3", "nombre": "X", "tipo_vehiculo": "carro",
                                   "inicio": "2036-06-12 08:00:00", "fin": "2036-06-12 09:00:00"}),
        ("Fuera de rango (ocupación 500 con capacidad 100)", None),
        ("Formato incorrecto (fecha)", {"codigo_zona": "CARRO01", "fecha_hora": "31/12/2016", "ocupacion": 5}),
    ]:
        if cuerpo is None:
            mostrar(nombre, c.post("/lecturas", json={"codigo_zona": "CARRO01",
                                                     "fecha_hora": "2016-12-20 09:00:00", "ocupacion": 500}))
        elif "fecha_hora" in cuerpo:
            mostrar(nombre, c.post("/lecturas", json=cuerpo))
        else:
            mostrar(nombre, c.post("/reservas", json=cuerpo))

    paso(7, "La decisión: validar en la API y escapar en la interfaz")
    salida.append("Decisión: las reglas viven en app/reglas.py y se aplican igual en API y pipeline. "
                  "Descartado: validar solo en el navegador, porque cualquiera puede llamar la API directamente.")
    print(salida[-1])

destino = RAIZ / "evidencias" / "08_momento3.txt"
destino.parent.mkdir(exist_ok=True)
destino.write_text("\n".join(salida), encoding="utf-8")
print(f"\nEvidencia guardada en {destino}")
