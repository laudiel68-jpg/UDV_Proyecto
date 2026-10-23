"""Integración con la base real del G1 y el login real del G2 (Alta 2 y 3).

Corre contra un MySQL con db_udv recién creada por el G1:

    python -m g1_bd crear --host 127.0.0.1 --user root --password <clave>
    set G6_MYSQL_URL=mysql+pymysql://root:<clave>@127.0.0.1:3306/db_udv
    python -m pytest tests/integracion

Sin G6_MYSQL_URL se omite. Usa la semilla del G1 (usuarios demo con la
contraseña de prueba que publica el G1) y deja registros nuevos con códigos
G6T-..., así que úsala solo con una base de pruebas, nunca la compartida.
"""

import os
import uuid

import pytest

URL = os.getenv("G6_MYSQL_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Define G6_MYSQL_URL para probar con MySQL")

if URL:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from g2_api.database import get_db
    from g2_api.middleware.error_handler import register_error_handlers
    from g2_api.routers import auth
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from g6_admin import api, tablas

CONTRASENA_DEMO = "Demo2026!"  # Pública en el README del G1; solo datos de prueba.


@pytest.fixture(scope="module")
def fabrica():
    motor = create_engine(URL, pool_pre_ping=True)
    with motor.connect() as conexion:
        conexion.execute(text("SELECT 1 FROM sede LIMIT 1"))
    yield sessionmaker(bind=motor)
    motor.dispose()


@pytest.fixture(scope="module")
def cliente(fabrica):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth.router)       # login real del G2
    app.include_router(auth.me_router)
    app.include_router(api.router)

    def sesion():
        with fabrica() as s:
            yield s

    app.dependency_overrides[get_db] = sesion
    return TestClient(app)


def entrar(cliente, correo):
    respuesta = cliente.post("/api/v1/auth/login",
                             json={"correo": correo, "password": CONTRASENA_DEMO})
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin(cliente):
    return entrar(cliente, "admin@demo.udv.edu.gt")


@pytest.fixture(scope="module")
def docente(cliente):
    return entrar(cliente, "docente1@demo.udv.edu.gt")


def codigo():
    return f"G6T-{uuid.uuid4().hex[:6].upper()}"


# ── Login del G2 + permisos (Alta 3) ───────────────────────────────────────

def test_sin_token_da_401_y_el_docente_no_modifica(cliente, docente):
    assert cliente.get("/api/v1/campuses").status_code == 401
    respuesta = cliente.post("/api/v1/campuses", headers=docente,
                             json={"code": codigo(), "name": "Sin permiso"})
    assert respuesta.status_code == 403


# ── Catálogos en las tablas del G1 (Alta 1 y 2) ────────────────────────────

def test_lista_la_semilla_del_g1(cliente, docente):
    sedes = cliente.get("/api/v1/campuses", headers=docente).json()["data"]
    assert {"S-CEN", "S-REG"} <= {s["code"] for s in sedes}
    periodos = cliente.get("/api/v1/periods?q=2026-2", headers=docente).json()["data"]
    assert periodos[0]["start_date"] == "2026-07-06"


@pytest.mark.parametrize("recurso, datos", [
    ("campuses", {"name": "Sede de prueba G6", "address": "Zona 1"}),
    ("academic-units", {"name": "Unidad de prueba G6", "faculty_id": 1, "campus_id": 1}),
    ("courses", {"name": "Curso de prueba G6", "credits": 3}),
    ("modalities", {"name": "Modalidad G6"}),
    ("areas", {"name": "Área G6"}),
])
def test_crear_y_modificar_quedan_en_mysql_con_auditoria(cliente, admin, fabrica,
                                                         recurso, datos):
    creado = cliente.post(f"/api/v1/{recurso}", headers=admin,
                          json={"code": codigo(), **datos})
    assert creado.status_code == 201, creado.text
    registro = creado.json()

    cambio = cliente.patch(f"/api/v1/{recurso}/{registro['id']}", headers=admin,
                           json={"is_active": False})
    assert cambio.status_code == 200 and cambio.json()["is_active"] is False

    tabla = api.CATALOGOS[recurso].tabla
    auditoria = cliente.get(f"/api/v1/audit?entity={tabla.name}&per_page=100",
                            headers=admin).json()["data"]
    propias = [a for a in auditoria if a["entity_id"] == registro["id"]]
    assert [a["action"] for a in propias] == ["update", "insert"]
    assert propias[0]["actor_id"] == 1  # admin de la semilla


def test_periodo_nuevo_y_duplicado(cliente, admin):
    datos = {"code": codigo(), "year": 2031, "cycle": 2,
             "start_date": "2031-07-01", "end_date": "2031-11-30"}
    primera = cliente.post("/api/v1/periods", headers=admin, json=datos)
    if primera.status_code == 409:  # ya se corrió antes sobre esta base
        pytest.skip("El ciclo de prueba ya existe en esta base")
    assert primera.status_code == 201
    repetido = cliente.post("/api/v1/periods", headers=admin, json={**datos, "code": codigo()})
    assert repetido.status_code == 409


# ── Auditoría transversal (G6-14, G6-30 a G6-33) ───────────────────────────

def test_la_auditoria_muestra_tambien_lo_de_los_triggers_y_el_login(cliente, admin):
    usuarios = cliente.get("/api/v1/audit?entity=usuario&action=insert",
                           headers=admin).json()
    assert usuarios["total"] >= 8  # alta de los usuarios de la semilla del G1


def test_mysql_no_deja_editar_la_auditoria(fabrica):
    with fabrica() as s, pytest.raises(OperationalError):
        s.execute(text("UPDATE auditoria SET accion = 'x' ORDER BY id LIMIT 1"))


# ── Eventos de los triggers → notificaciones (G6-17) ───────────────────────

def test_los_eventos_pendientes_se_vuelven_notificaciones(cliente, admin, fabrica):
    respuesta = cliente.post("/api/v1/notifications/process", headers=admin)
    assert respuesta.status_code == 200
    assert respuesta.json()["failed"] == 0
    with fabrica() as s:
        pendientes = s.execute(select(tablas.evento.c.id).where(
            tablas.evento.c.procesado_en.is_(None))).all()
        avisos_de_evento = s.execute(select(tablas.notificacion.c.id).where(
            tablas.notificacion.c.evento_id.is_not(None))).all()
    assert pendientes == []
    assert len(avisos_de_evento) >= 2


def test_cancelar_una_tarea_avisa_a_sus_destinatarios(cliente, fabrica):
    with fabrica() as s:
        tarea = s.execute(text(
            "SELECT t.id, td.usuario_id FROM tarea t JOIN tarea_destinatario td "
            "ON td.tarea_id = t.id WHERE t.estado_codigo NOT IN ('draft', 'cancelled', 'closed') "
            "ORDER BY t.id LIMIT 1")).first()
        if tarea is None:
            pytest.skip("No quedan tareas para cancelar en esta base")
        # Lo que haría el G3: cancelar la tarea. El trigger del G1 crea el evento.
        s.execute(text("UPDATE tarea SET estado_codigo = 'cancelled' WHERE id = :id"),
                  {"id": tarea.id})
        s.commit()
        correo = s.execute(text("SELECT correo FROM usuario WHERE id = :id"),
                           {"id": tarea.usuario_id}).scalar_one()

    destinatario = entrar(cliente, correo)
    avisos = cliente.get("/api/v1/notifications", headers=destinatario).json()["data"]
    assert any(a["event"] == "task.cancelled" for a in avisos)


def test_marcar_leida_en_mysql(cliente, docente):
    avisos = cliente.get("/api/v1/notifications?unread=true", headers=docente).json()["data"]
    if not avisos:
        pytest.skip("El docente no tiene avisos sin leer")
    respuesta = cliente.patch(f"/api/v1/notifications/{avisos[0]['id']}/read", headers=docente)
    assert respuesta.status_code == 200 and respuesta.json()["is_read"] is True
