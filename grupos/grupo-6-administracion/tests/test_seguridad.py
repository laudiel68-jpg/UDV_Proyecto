"""G6-20 y G6-36: datos semilla y registros sin contraseñas ni secretos.

Revisa el código del G6, la semilla del G1 y los datos de prueba del G2 (si
están en la rama), y que la API del G6 no muestre secretos aunque estén
guardados en la base.
"""

import json
import logging
import re
from pathlib import Path

import pytest
from sqlalchemy import insert

from g6_admin import tablas
from g6_admin.notificaciones import RepositorioNotificaciones, ServicioNotificaciones

CARPETA_G6 = Path(__file__).resolve().parents[1]
GRUPOS = CARPETA_G6.parent
SEMILLA_G1 = GRUPOS / "grupo-1-base-de-datos" / "Docs" / "sql" / "02_seed.sql"
PRUEBA_G2 = GRUPOS / "grupo-2-api-seguridad" / "g2_api" / "datos_prueba" / "usuarios_prueba.json"

# Lo que delata un secreto escrito en un archivo.
PATRONES = {
    "URL con contraseña": re.compile(r"\w+://[^\s:/@]+:(?!\*\*\*|<clave>)[^\s@/]{3,}@"),
    "llave privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "token de GitHub": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "clave de AWS": re.compile(r"AKIA[0-9A-Z]{16}"),
    "SECRET_KEY con valor": re.compile(r"SECRET_KEY\s*=\s*['\"]?[^\s'\"<]{8,}"),
}
# Valores falsos a propósito, solo dentro de las pruebas.
PERMITIDOS_EN_PRUEBAS = ("clave-solo-para-pruebas", "Xq81", "raiz", "<clave>", "cambiar",
                         "usuario:clave@servidor")


def archivos_del_g6():
    for ruta in CARPETA_G6.rglob("*"):
        if ruta.is_file() and ruta.suffix in {".py", ".md", ".html", ".txt", ".ini", ".env",
                                              ".example", ".json", ".yml", ".yaml"}:
            if "__pycache__" not in ruta.parts and ".pytest_cache" not in ruta.parts:
                yield ruta


def test_no_hay_archivos_env_en_la_carpeta():
    assert [r.name for r in CARPETA_G6.rglob(".env")] == []


@pytest.mark.parametrize("nombre", list(PATRONES))
def test_el_codigo_del_g6_no_tiene_secretos(nombre):
    hallazgos = []
    for ruta in archivos_del_g6():
        for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            if PATRONES[nombre].search(linea):
                en_pruebas = "tests" in ruta.relative_to(CARPETA_G6).parts
                if not (en_pruebas and any(p in linea for p in PERMITIDOS_EN_PRUEBAS)):
                    hallazgos.append(f"{ruta.relative_to(CARPETA_G6)}:{numero}")
    assert hallazgos == []


@pytest.mark.skipif(not SEMILLA_G1.exists(), reason="La semilla del G1 no está en esta rama")
def test_la_semilla_del_g1_solo_guarda_hashes_y_correos_de_demo():
    texto = SEMILLA_G1.read_text(encoding="utf-8")
    bloque = texto[texto.index("insert into usuario "):]
    bloque = bloque[:bloque.index(";")]
    filas = re.findall(r"\((\d+),\s*'([^']+)',.*?'([^']*)',\s*\d+,\s*\d\)", bloque)
    assert len(filas) >= 8
    for _, correo, hash_ in filas:
        assert correo.endswith("@demo.udv.edu.gt"), correo
        assert re.fullmatch(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}", hash_), "no es bcrypt"


@pytest.mark.skipif(not PRUEBA_G2.exists(), reason="Los datos de prueba del G2 no están")
def test_los_datos_de_prueba_del_g2_no_traen_contrasenas():
    datos = PRUEBA_G2.read_text(encoding="utf-8").lower()
    assert not any(c in datos for c in ('"password"', '"contrasena"', '"contraseña"', '"clave"'))


def test_la_auditoria_oculta_campos_secretos(admin, fabrica):
    detalle = {"despues": {"correo": "a@demo.udv.edu.gt", "hash_contrasena": "$2b$10$abc",
                           "token": "eyJ...", "cambio_contrasena": True}}
    with fabrica.begin() as s:
        s.execute(insert(tablas.auditoria).values(
            tabla="usuario", registro_id="9", accion="update", actor_id=1,
            detalle=json.dumps(detalle)))

    [registro] = admin.get("/api/v1/audit?entity=usuario").json()["data"]

    assert registro["changes"]["despues"] == {
        "correo": "a@demo.udv.edu.gt", "hash_contrasena": "***", "token": "***",
        "cambio_contrasena": True}


def test_el_registro_de_errores_no_muestra_detalles(sesion, fabrica, caplog, monkeypatch):
    """G6-36: si un evento falla, el log dice el tipo de error, no el mensaje."""
    with fabrica.begin() as s:
        s.execute(insert(tablas.evento).values(nombre="task.published", clave_unica="x",
                                               tarea_id=1))
    servicio = ServicioNotificaciones(RepositorioNotificaciones(sesion))

    def falla(_fila):
        raise ConnectionError("mysql://udv_app:Xq81@10.0.0.5 no responde")

    monkeypatch.setattr(servicio, "_armar", falla)
    with caplog.at_level(logging.WARNING):
        assert servicio.procesar_pendientes()["failed"] == 1
    assert "ConnectionError" in caplog.text
    assert "Xq81" not in caplog.text and "10.0.0.5" not in caplog.text
