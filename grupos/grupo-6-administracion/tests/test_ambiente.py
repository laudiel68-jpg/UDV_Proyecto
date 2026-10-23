"""G6-35: desarrollo y demostración quedan separados y bien configurados."""

import pytest

from g6_admin import ambiente

CLAVE = "k3Jx9" * 8  # 40 caracteres que no parecen de ejemplo
DEMO = {"APP_ENV": "demostracion", "SECRET_KEY": CLAVE,
        "DATABASE_URL": "mysql+pymysql://udv_app:Xq81_vT2@mysql.railway.internal:3306/db_udv"}


def test_desarrollo_con_sqlite_es_valido():
    assert ambiente.revisar({"DATABASE_URL": "sqlite:///./dev.db", "SECRET_KEY": "x"}) == []


def test_demostracion_bien_configurada():
    assert ambiente.revisar(DEMO) == []


@pytest.mark.parametrize("cambio, texto", [
    ({"APP_ENV": "pruebas"}, "APP_ENV"),
    ({"DATABASE_URL": ""}, "Falta DATABASE_URL"),
    ({"DATABASE_URL": "sqlite:///./dev.db"}, "no SQLite"),
    ({"DATABASE_URL": "mysql+pymysql://udv_app:Xq81@127.0.0.1:3307/db_udv"}, "local"),
    ({"DATABASE_URL": "mysql+pymysql://root:Xq81@db.railway:3306/db_udv"}, "root"),
    ({"DATABASE_URL": "mysql+pymysql://udv_app:cambiar_clave_local@db.r:3306/db_udv"},
     "ejemplo"),
    ({"DATABASE_URL": "mysql+pymysql://udv_app:Xq81@db.railway:3306"}, "nombre de la base"),
    ({"SECRET_KEY": "corta"}, "SECRET_KEY"),
    ({"SECRET_KEY": "cambiar-esta-clave-por-una-larga-y-aleatoria"}, "SECRET_KEY"),
    ({"CORS_ORIGINS": "*"}, "CORS_ORIGINS"),
])
def test_demostracion_detecta_cada_problema(cambio, texto):
    problemas = ambiente.revisar(DEMO | cambio)
    assert any(texto in p for p in problemas), problemas


def test_ningun_mensaje_muestra_secretos():
    problemas = ambiente.revisar(DEMO | {"SECRET_KEY": "corta", "CORS_ORIGINS": "*",
                                         "DATABASE_URL": "mysql+pymysql://root:Xq81@localhost/db"})
    assert problemas and not any("Xq81" in p or "corta" in p for p in problemas)


def test_ocultar_url():
    assert ambiente.ocultar_url(DEMO["DATABASE_URL"]) == (
        "mysql+pymysql://udv_app:***@mysql.railway.internal:3306/db_udv")
    assert ambiente.ocultar_url("sqlite:///./dev.db") == "sqlite:///./dev.db"


def test_el_comando_sale_con_error_y_sin_secretos(monkeypatch, capsys):
    for nombre, valor in (DEMO | {"SECRET_KEY": "corta"}).items():
        monkeypatch.setenv(nombre, valor)
    assert ambiente.main() == 1
    salida = capsys.readouterr().out
    assert "Xq81_vT2" not in salida and "corta" not in salida
    assert "udv_app:***@" in salida
