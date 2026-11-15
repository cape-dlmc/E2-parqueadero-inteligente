"""Seguridad básica de la aplicación.

- Contraseñas: se guardan como hash PBKDF2-SHA256 con sal aleatoria. Nunca en texto plano.
- Texto libre: se rechaza el texto que parece código (etiquetas HTML, atributos con
  JavaScript) o que trae caracteres de control. La interfaz además escapa todo lo que muestra.
"""
import hashlib
import hmac
import os
import re

ITERACIONES = 200_000
PATRON_CODIGO = re.compile(r"[<>]|javascript:|\bon\w+\s*=", re.IGNORECASE)
PATRON_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def hash_clave(clave: str) -> str:
    sal = os.urandom(16)
    digesto = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, ITERACIONES)
    return f"pbkdf2_sha256${ITERACIONES}${sal.hex()}${digesto.hex()}"


def verificar_clave(clave: str, almacenado: str) -> bool:
    try:
        algoritmo, iteraciones, sal_hex, digesto_hex = almacenado.split("$")
    except ValueError:
        return False
    if algoritmo != "pbkdf2_sha256":
        return False
    digesto = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"),
                                  bytes.fromhex(sal_hex), int(iteraciones))
    return hmac.compare_digest(digesto.hex(), digesto_hex)


def texto_seguro(valor) -> bool:
    """False si el texto contiene etiquetas, atributos con código o caracteres de control."""
    texto = str(valor)
    return not (PATRON_CODIGO.search(texto) or PATRON_CONTROL.search(texto))
