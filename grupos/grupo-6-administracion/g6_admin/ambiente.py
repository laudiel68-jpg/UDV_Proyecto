"""Revisión de la configuración de cada ambiente (escenario G6-35).

El sistema se configura solo con variables de entorno (requerimientos de
despliegue del G6). Hay dos ambientes separados:

- desarrollo: la computadora de cada integrante; puede usar SQLite o el MySQL
  local de docker compose.
- demostracion: el despliegue público (Railway) con su propia base MySQL.

Uso, desde esta carpeta y con el .env cargado:

    python -m g6_admin.ambiente

Muestra qué falta o qué está mal sin imprimir nunca contraseñas ni claves, y
termina con código 1 si hay algún problema.
"""

import os
import sys
from collections.abc import Mapping
from urllib.parse import urlsplit

AMBIENTES = ("desarrollo", "demostracion")
CLAVE_MINIMA = 32
# Textos que delatan un valor copiado tal cual de un .env.example.
VALORES_DE_EJEMPLO = ("cambiar", "change", "example", "ejemplo", "secret", "123456")


def ocultar_url(url: str) -> str:
    """mysql+pymysql://usuario:<clave>@host/db → mysql+pymysql://usuario:***@host/db"""
    partes = urlsplit(url)
    if partes.password is None:
        return url
    usuario = partes.username or ""
    host = partes.hostname or ""
    puerto = f":{partes.port}" if partes.port else ""
    return f"{partes.scheme}://{usuario}:***@{host}{puerto}{partes.path}"


def revisar(variables: Mapping[str, str]) -> list[str]:
    """Problemas de configuración del ambiente. Lista vacía = todo bien."""
    problemas: list[str] = []
    ambiente = variables.get("APP_ENV", "desarrollo")
    if ambiente not in AMBIENTES:
        problemas.append(f"APP_ENV debe ser {' o '.join(AMBIENTES)}.")
    publico = ambiente == "demostracion"

    url = variables.get("DATABASE_URL", "")
    if not url:
        problemas.append("Falta DATABASE_URL (la conexión a la base del G1).")
    else:
        partes = urlsplit(url)
        if publico and not partes.scheme.startswith(("mysql", "mariadb")):
            problemas.append("En demostracion la base debe ser MySQL, no SQLite.")
        if partes.scheme.startswith(("mysql", "mariadb")):
            if partes.path.strip("/") == "":
                problemas.append("DATABASE_URL no dice el nombre de la base (…/db_udv).")
            if publico and partes.username == "root":
                problemas.append("En demostracion no uses el usuario root de MySQL.")
            if publico and partes.hostname in ("localhost", "127.0.0.1"):
                problemas.append("En demostracion la base no puede ser la local "
                                 "(sería la misma de desarrollo).")
            if publico and _parece_de_ejemplo(partes.password or ""):
                problemas.append("La contraseña de la base parece la del ejemplo.")

    clave = variables.get("SECRET_KEY", "")
    if not clave:
        problemas.append("Falta SECRET_KEY (la usa el login del G2).")
    elif publico and (len(clave) < CLAVE_MINIMA or _parece_de_ejemplo(clave)):
        problemas.append(f"En demostracion SECRET_KEY debe ser aleatoria y de "
                         f"{CLAVE_MINIMA} caracteres o más.")

    if publico and "*" in variables.get("CORS_ORIGINS", ""):
        problemas.append("En demostracion CORS_ORIGINS no puede ser *.")
    return problemas


def _parece_de_ejemplo(valor: str) -> bool:
    return any(texto in valor.lower() for texto in VALORES_DE_EJEMPLO)


def main() -> int:
    try:
        from dotenv import load_dotenv  # La instala el G2 (python-dotenv).
        load_dotenv()
    except ImportError:
        pass
    variables = dict(os.environ)
    ambiente = variables.get("APP_ENV", "desarrollo")
    print(f"Ambiente: {ambiente}")
    print(f"Base: {ocultar_url(variables.get('DATABASE_URL', '(sin definir)'))}")
    problemas = revisar(variables)
    for problema in problemas:
        print(f"  ✗ {problema}")
    if not problemas:
        print("  ✓ Configuración completa.")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
