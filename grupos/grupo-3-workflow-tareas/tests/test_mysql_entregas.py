"""submit/resubmit contra una base MySQL REAL (esquema y semilla de G1).

Los tests con SQLite no pueden ver esto: dependen de requiere_archivo del tipo de tarea y de las
tablas entrega/archivo. Se omiten solos si no defines la base:

    set G3_TEST_MYSQL_URL=mysql+pymysql://usuario:clave@host:3306/db_udv
    py -m pytest tests/test_mysql_entregas.py -v

ESCRIBEN en la base (crean una tarea y la entregan; G1 no permite borrar entregas ni
transiciones), asÃ­ que Ãºsalos solo con una base de pruebas, nunca la compartida.

El vÃ­nculo archivo -> entrega lo hace G4 al vincular el archivo (CONTRATO.md Â§4); aquÃ­ se imita
con SQL directo (`_vincular_como_g4`) para probar solo la parte de G3.
"""
import os
import uuid
from datetime import date, timedelta

import pytest

URL = os.environ.get("G3_TEST_MYSQL_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Define G3_TEST_MYSQL_URL para probar con MySQL")

if URL:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from workflow import transitions
    from workflow.api import router
    from workflow.auth import current_user
    from workflow.db import connect
    from workflow.deps import get_conn
    from workflow.http_errors import register_error_handlers

P = "/api/v1"
COORDINADOR, DOCENTE, OTRO_DOCENTE, REVISOR = 2, 3, 8, 5      # usuarios de la semilla de G1
TIPO_CON_ARCHIVO, TIPO_SIN_ARCHIVO = 2, 4                     # SUBIR_CV / CONFIRMAR_ACTIVIDAD


@pytest.fixture
def api():
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    quien = {"id": COORDINADOR}

    def conexion():
        c = connect(URL)
        try:
            yield c
        finally:
            c.close()

    def usuario():
        c = connect(URL)
        try:
            return transitions.get_actor(c, quien["id"])
        finally:
            c.close()

    app.dependency_overrides[get_conn] = conexion
    app.dependency_overrides[current_user] = usuario
    cliente = TestClient(app)
    cliente.como = lambda uid: quien.update(id=uid)
    return cliente


def _asignacion_en_progreso(api, tipo):
    """Crea una tarea del tipo dado, la publica al docente y la deja en in_progress."""
    api.como(COORDINADOR)
    t = api.post(f"{P}/tasks", json={
        "type_id": tipo, "title": f"G3T-{uuid.uuid4().hex[:8]}", "description": "prueba",
        "due_date": str(date.today() + timedelta(days=30)), "reviewer_id": REVISOR})
    assert t.status_code == 201, t.text
    tid = t.json()["id"]
    assert api.post(f"{P}/tasks/{tid}/recipients",
                    json={"mode": "users", "user_ids": [DOCENTE]}).status_code == 200
    assert api.post(f"{P}/tasks/{tid}/publish").status_code == 200
    asig = api.get(f"{P}/tasks/{tid}/assignments").json()["data"][0]["id"]
    api.como(DOCENTE)
    assert api.post(f"{P}/assignments/{asig}/start").status_code == 200
    return asig


def _vincular_como_g4(asig, borrador=None):
    """Imita a G4 al vincular un archivo: crea la entrega del intento (MAX + 1) y le enlaza un
    archivo nuevo."""
    nombre = uuid.uuid4().hex
    c = connect(URL)
    try:
        c.execute("INSERT INTO entrega (tarea_destinatario_id, numero_intento, entregado_por, contenido_texto)"
                  " SELECT ?, COALESCE(MAX(numero_intento), 0) + 1, ?, ? FROM entrega"
                  " WHERE tarea_destinatario_id = ?", (asig, DOCENTE, borrador, asig))
        entrega = c.execute("SELECT id FROM entrega WHERE tarea_destinatario_id = ?"
                            " ORDER BY numero_intento DESC LIMIT 1", (asig,)).fetchone()["id"]
        c.execute("INSERT INTO archivo (nombre_original, nombre_interno, tipo_mime, tamano_bytes,"
                  " hash_sha256, ubicacion, autor_id, entrega_id)"
                  " VALUES (?, ?, 'application/pdf', 10, ?, 'uploads/x', ?, ?)",
                  (f"{nombre}.pdf", f"{nombre}.pdf", "0" * 64, DOCENTE, entrega))
        c.commit()
    finally:
        c.close()


def _consulta(sql, params=()):
    c = connect(URL)
    try:
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    finally:
        c.close()


def _estado(asig):
    return _consulta("SELECT estado_codigo AS e FROM tarea_destinatario WHERE id = ?", (asig,))[0]["e"]


def _entregas(asig):
    return [(r["numero_intento"], r["contenido_texto"]) for r in _consulta(
        "SELECT numero_intento, contenido_texto FROM entrega WHERE tarea_destinatario_id = ?"
        " ORDER BY numero_intento", (asig,))]


def test_submit_sin_archivo_en_tipo_que_lo_requiere_responde_422_y_no_cambia_nada(api):
    asig = _asignacion_en_progreso(api, TIPO_CON_ARCHIVO)
    r = api.post(f"{P}/assignments/{asig}/submit")
    assert r.status_code == 422, r.text                          # antes: 200
    assert _estado(asig) == "in_progress" and _entregas(asig) == []


def test_submit_con_archivo_vinculado_funciona_y_usa_la_entrega_existente(api):
    asig = _asignacion_en_progreso(api, TIPO_CON_ARCHIVO)
    _vincular_como_g4(asig, borrador="mi borrador")
    r = api.post(f"{P}/assignments/{asig}/submit")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted"
    assert _entregas(asig) == [(1, "mi borrador")]               # no se creÃ³ un segundo intento


def test_submit_en_tipo_sin_archivo_crea_la_entrega_si_no_existe(api):
    asig = _asignacion_en_progreso(api, TIPO_SIN_ARCHIVO)
    r = api.post(f"{P}/assignments/{asig}/submit")
    assert r.status_code == 200, r.text
    assert [n for n, _ in _entregas(asig)] == [1]


def test_resubmit_con_archivo_nuevo_y_sin_el(api):
    asig = _asignacion_en_progreso(api, TIPO_CON_ARCHIVO)
    _vincular_como_g4(asig)                                      # intento 1
    assert api.post(f"{P}/assignments/{asig}/submit").status_code == 200
    api.como(REVISOR)
    assert api.post(f"{P}/assignments/{asig}/review").status_code == 200
    assert api.post(f"{P}/assignments/{asig}/return", json={"comment": "corrige"}).status_code == 200
    api.como(DOCENTE)
    # el archivo del intento 1 no cuenta para el reenvÃ­o: sin archivo nuevo, 422
    r = api.post(f"{P}/assignments/{asig}/resubmit")
    assert r.status_code == 422, r.text
    assert _estado(asig) == "returned" and len(_entregas(asig)) == 1
    # con archivo nuevo (intento 2, vinculado por G4) pasa y usa esa entrega
    _vincular_como_g4(asig)
    r = api.post(f"{P}/assignments/{asig}/resubmit")
    assert r.status_code == 200, r.text
    assert [n for n, _ in _entregas(asig)] == [1, 2]             # sin intentos de mÃ¡s


def test_el_orden_de_errores_se_mantiene_403_antes_que_422(api):
    asig = _asignacion_en_progreso(api, TIPO_CON_ARCHIVO)
    api.como(OTRO_DOCENTE)
    assert api.post(f"{P}/assignments/{asig}/submit").status_code == 403
