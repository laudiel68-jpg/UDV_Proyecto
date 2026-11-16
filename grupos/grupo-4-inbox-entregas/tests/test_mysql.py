"""Pruebas de G4 contra una base MySQL REAL (con 01_schema.sql y 02_seed.sql de G1).

Las demás pruebas usan datos de ejemplo en memoria y por eso no pueden detectar
errores en el camino de MySQL (por ejemplo una función que no existe en
database.py). Estas sí. Se omiten solas si no defines la base:

    set G4_TEST_MYSQL_URL=mysql+pymysql://usuario:clave@host:3306/db_udv
    py -m pytest tests/test_mysql.py -v

Solo hacen lecturas, así que se pueden correr contra la base compartida.
"""
import os

import pytest

URL = os.environ.get("G4_TEST_MYSQL_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Define G4_TEST_MYSQL_URL para probar contra MySQL")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import g4_inbox.database as database
import g4_inbox.routes as routes
from g2_api.routers.auth import obtener_usuario_actual
from g4_inbox.main import app


class _Rol:
    def __init__(self, codigo):
        self.codigo = codigo


class _Usuario:
    def __init__(self, id, roles=("teacher",)):
        self.id = id
        self.roles = [_Rol(r) for r in roles]


@pytest.fixture
def cliente(monkeypatch):
    motor = create_engine(URL, pool_pre_ping=True)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=motor))
    monkeypatch.setattr(routes, "USAR_MYSQL", True)
    yield TestClient(app)
    app.dependency_overrides.clear()
    motor.dispose()


def entrar_como(id_usuario, roles=("teacher",)):
    app.dependency_overrides[obtener_usuario_actual] = lambda: _Usuario(id_usuario, roles)


@pytest.fixture
def dueno_y_asignacion(cliente):
    """Un docente real con tareas, una de sus asignaciones, y otro docente distinto."""
    with database.SessionLocal() as s:
        fila = s.execute(text("SELECT usuario_id, asignacion_id FROM v_inbox LIMIT 1")).first()
        otro = s.execute(text("SELECT DISTINCT usuario_id FROM v_inbox WHERE usuario_id <> :u LIMIT 1"),
                         {"u": fila[0]}).first()
    return fila[0], fila[1], (otro[0] if otro else fila[0] + 1000)


def test_el_inbox_responde_200_con_mysql_y_trae_solo_las_tareas_del_usuario(cliente, dueno_y_asignacion):
    uid, _, _ = dueno_y_asignacion
    entrar_como(uid)
    respuesta = cliente.get("/api/v1/inbox")
    assert respuesta.status_code == 200, respuesta.text   # antes: 500 (falta fetch_orden_prioridades)
    cuerpo = respuesta.json()
    assert cuerpo["total"] >= 1
    assert all(item["assignee_id"] == uid for item in cuerpo["data"])


def test_el_resumen_funciona_con_mysql(cliente, dueno_y_asignacion):
    entrar_como(dueno_y_asignacion[0])
    assert cliente.get("/api/v1/inbox/summary").status_code == 200


def test_el_orden_de_prioridad_sale_del_catalogo_de_g1(cliente):
    assert database.fetch_orden_prioridades() == {"low": 1, "medium": 2, "high": 3, "urgent": 4}


def test_el_detalle_lee_de_mysql_y_trae_si_requiere_archivo(cliente, dueno_y_asignacion):
    uid, aid, _ = dueno_y_asignacion
    entrar_como(uid)
    respuesta = cliente.get(f"/api/v1/assignments/{aid}")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["id"] == aid and cuerpo["assignee_id"] == uid
    assert isinstance(cuerpo["requiere_archivo"], bool)


def test_otro_docente_recibe_403_con_datos_reales(cliente, dueno_y_asignacion):
    _, aid, otro = dueno_y_asignacion
    entrar_como(otro, roles=("teacher",))
    assert cliente.get(f"/api/v1/assignments/{aid}").status_code == 403


def test_solo_el_revisor_designado_ve_el_detalle_con_datos_reales(cliente):
    with database.SessionLocal() as s:
        fila = s.execute(text("""
            SELECT td.id, t.revisor_id FROM tarea_destinatario td
            JOIN tarea t ON t.id = td.tarea_id
            WHERE t.revisor_id IS NOT NULL LIMIT 1""")).first()
    if fila is None:
        pytest.skip("La base no tiene tareas con revisor designado")
    aid, revisor = fila
    entrar_como(revisor, roles=("teacher", "reviewer"))
    assert cliente.get(f"/api/v1/assignments/{aid}").status_code == 200
    entrar_como(999999, roles=("teacher", "reviewer"))   # revisor, pero no de esta tarea
    assert cliente.get(f"/api/v1/assignments/{aid}").status_code == 403
