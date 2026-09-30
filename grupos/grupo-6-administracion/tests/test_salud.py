"""Pruebas de GET /api/v1/health: escenarios G6-34 y G6-36."""

import time
from datetime import datetime

from g6_admin.salud import estado_del_servicio

CAMPOS = {"status", "service", "version", "environment", "time",
          "uptime_seconds", "checks"}


def test_health_responde_sin_iniciar_sesion(cliente):
    respuesta = cliente.get("/api/v1/health")
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "ok"
    assert respuesta.headers["cache-control"] == "no-store"


def test_health_tiene_solo_los_campos_esperados(cliente):
    assert set(cliente.get("/api/v1/health").json()) == CAMPOS


def test_health_usa_fecha_iso_8601(cliente):
    fecha = cliente.get("/api/v1/health").json()["time"]
    assert datetime.fromisoformat(fecha).tzinfo is not None


def test_health_toma_entorno_y_version_de_variables(cliente, monkeypatch):
    monkeypatch.setenv("APP_ENV", "demostracion")
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    datos = cliente.get("/api/v1/health").json()
    assert (datos["environment"], datos["version"]) == ("demostracion", "1.2.3")


def test_health_no_expone_secretos_del_entorno(cliente, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "valor-secreto-de-prueba")
    monkeypatch.setenv("DATABASE_URL", "postgresql://usuario:clave@servidor/bd")
    texto = cliente.get("/api/v1/health").text
    assert "valor-secreto-de-prueba" not in texto
    assert "clave@servidor" not in texto


def test_verificacion_fallida_marca_degradado_sin_detalles_internos():
    def base_caida():
        raise ConnectionError("password=abc123 host=10.0.0.5")

    estado = estado_del_servicio(iniciado_en=time.monotonic(), entorno="desarrollo",
                                 version="0.1.0", verificaciones={"database": base_caida})
    assert estado["status"] == "degraded"
    assert estado["checks"] == {"database": "error"}
    assert "abc123" not in str(estado) and "10.0.0.5" not in str(estado)


def test_verificacion_con_resultado_desconocido_cuenta_como_error():
    estado = estado_del_servicio(iniciado_en=time.monotonic(), entorno="desarrollo",
                                 version="0.1.0", verificaciones={"cola": lambda: "tal vez"})
    assert estado["checks"] == {"cola": "error"}


def test_health_responde_503_si_una_verificacion_falla(cliente, monkeypatch):
    import g6_admin.salud as salud

    def base_caida():
        raise ConnectionError("sin conexión")

    monkeypatch.setitem(salud.VERIFICACIONES_PREDETERMINADAS, "database", base_caida)
    respuesta = cliente.get("/api/v1/health")
    assert respuesta.status_code == 503
    assert respuesta.json()["status"] == "degraded"
