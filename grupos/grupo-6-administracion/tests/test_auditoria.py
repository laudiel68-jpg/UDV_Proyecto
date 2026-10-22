"""Pruebas de auditoría: escenarios G6-14, G6-15 y G6-30 a G6-33."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from g6_admin.app_demo import crear_app_demo
from g6_admin.auditoria import RepositorioAuditoriaEnMemoria, ServicioAuditoria
from g6_admin.errores import ErrorApi
from g6_admin.seguridad import USUARIOS_DEMO

ADMIN = {"X-Demo-Role": "admin"}
DOCENTE = {"X-Demo-Role": "teacher"}
ID_ADMIN = USUARIOS_DEMO["admin"].id
ID_DOCENTE = USUARIOS_DEMO["teacher"].id
HOY = datetime.now(timezone.utc).date().isoformat()  # La auditoría guarda en UTC

TRANSICION = {"actor_id": ID_DOCENTE, "entidad": "assignment", "entidad_id": 58,
              "estado_anterior": "in_progress", "estado_nuevo": "submitted",
              "comentario": "Entrego la planificación."}


@pytest.fixture
def servicio() -> ServicioAuditoria:
    return ServicioAuditoria(RepositorioAuditoriaEnMemoria())


@pytest.fixture
def app():
    return crear_app_demo(auth_demo=True, datos_ejemplo=False)


@pytest.fixture
def cliente(app) -> TestClient:
    return TestClient(app)


def auditoria(cliente, consulta="", encabezados=ADMIN):
    return cliente.get(f"/api/v1/audit{consulta}", headers=encabezados)


# ── G6-14: una acción auditada queda registrada ───────────────────────────

def test_crear_un_registro_de_catalogo_queda_auditado(cliente):
    creado = cliente.post("/api/v1/campuses", json={"code": "norte", "name": "Sede Norte"},
                          headers=ADMIN).json()

    registros = auditoria(cliente).json()["data"]

    assert len(registros) == 1
    registro = registros[0]
    assert (registro["actor_id"], registro["action"]) == (ID_ADMIN, "create")
    assert (registro["entity"], registro["entity_id"]) == ("campuses", creado["id"])
    assert registro["changes"] == {"code": "NORTE", "name": "Sede Norte", "is_active": True}
    assert registro["created_at"].startswith(HOY)


def test_modificar_un_registro_de_catalogo_queda_auditado(cliente):
    creado = cliente.post("/api/v1/areas", json={"code": "SIS", "name": "Sistemas"},
                          headers=ADMIN).json()
    cliente.patch(f"/api/v1/areas/{creado['id']}", json={"is_active": False}, headers=ADMIN)
    # Un cambio rechazado (docente) no se audita.
    cliente.patch(f"/api/v1/areas/{creado['id']}", json={"name": "Otra"}, headers=DOCENTE)

    ultimo = auditoria(cliente).json()["data"][0]

    assert auditoria(cliente).json()["total"] == 2
    assert (ultimo["action"], ultimo["entity"], ultimo["entity_id"]) == (
        "update", "areas", creado["id"])
    assert ultimo["changes"] == {"is_active": False}


def test_una_operacion_rechazada_no_deja_registro(cliente):
    cliente.post("/api/v1/campuses", json={"code": "NORTE", "name": "Sede"}, headers=DOCENTE)
    cliente.post("/api/v1/campuses", json={"code": "x"}, headers=ADMIN)
    assert auditoria(cliente).json()["total"] == 0


def test_registrar_accion_valida_los_datos(servicio):
    with pytest.raises(ErrorApi) as error:
        servicio.registrar(actor_id=0, accion="", entidad=None, entidad_id="5")
    assert set(error.value.detalles) == {"actor_id", "action", "entity", "entity_id"}


def test_la_auditoria_no_se_puede_editar_ni_borrar(servicio):
    registro = servicio.registrar(actor_id=1, accion="create", entidad="areas", entidad_id=1)
    # El repositorio no ofrece métodos para cambiar ni borrar.
    assert not any(hasattr(servicio.repositorio, m)
                   for m in ("modificar", "actualizar", "borrar", "eliminar"))
    # Cambiar el diccionario devuelto no altera lo guardado.
    registro["changes"]["code"] = "OTRO"
    assert servicio.repositorio.listar()[0].cambios == {}
    with pytest.raises(AttributeError):
        servicio.repositorio.listar()[0].accion = "delete"


# ── G6-15: una transición guarda actor, fecha, estados y comentario ───────

def test_transicion_registra_lo_que_pide_el_contrato(app, cliente):
    app.state.g6_auditoria.registrar_transicion(**TRANSICION)

    registro = auditoria(cliente).json()["data"][0]

    assert registro["action"] == "transition"
    assert registro["actor_id"] == ID_DOCENTE
    assert registro["created_at"].startswith(HOY)
    assert (registro["from_state"], registro["to_state"]) == ("in_progress", "submitted")
    assert registro["comment"] == "Entrego la planificación."


def test_transicion_de_programa_usa_los_estados_de_programa(servicio):
    servicio.registrar_transicion(actor_id=ID_ADMIN, entidad="program_version",
                                  entidad_id=3, estado_anterior="approved",
                                  estado_nuevo="authorized")
    with pytest.raises(ErrorApi) as error:
        # "closed" es de tareas, no de programas.
        servicio.registrar_transicion(actor_id=ID_ADMIN, entidad="program_version",
                                      entidad_id=3, estado_anterior="authorized",
                                      estado_nuevo="closed")
    assert "to_state" in error.value.detalles


@pytest.mark.parametrize("cambio, campo", [
    ({"estado_anterior": "enviado"}, "from_state"),
    ({"estado_nuevo": "SUBMITTED"}, "to_state"),
    ({"estado_nuevo": "in_progress"}, "to_state"),
    ({"entidad": "campuses"}, "entity"),
    ({"entidad": ["assignment"]}, "entity"),
    ({"comentario": None}, "comment"),
    ({"comentario": "x" * 1001}, "comment"),
    ({"actor_id": True}, "actor_id"),
])
def test_transicion_invalida_da_422_y_no_se_guarda(servicio, cambio, campo):
    with pytest.raises(ErrorApi) as error:
        servicio.registrar_transicion(**(TRANSICION | cambio))
    assert error.value.estado_http == 422
    assert campo in error.value.detalles
    assert servicio.repositorio.listar() == []


def test_transicion_no_entra_por_registrar(servicio):
    with pytest.raises(ErrorApi):
        servicio.registrar(actor_id=1, accion="transition", entidad="assignment", entidad_id=1)


# ── G6-30 a G6-33: filtros por usuario, fecha, entidad y acción ───────────

@pytest.fixture
def con_registros(app, cliente):
    auditoria_app = app.state.g6_auditoria
    cliente.post("/api/v1/campuses", json={"code": "NORTE", "name": "Sede Norte"}, headers=ADMIN)
    cliente.post("/api/v1/areas", json={"code": "SIS", "name": "Sistemas"}, headers=ADMIN)
    auditoria_app.registrar_transicion(**TRANSICION)
    auditoria_app.registrar_transicion(**TRANSICION | {
        "actor_id": ID_ADMIN, "estado_anterior": "submitted", "estado_nuevo": "under_review"})
    return cliente


def test_filtra_por_usuario(con_registros):
    datos = auditoria(con_registros, f"?user_id={ID_DOCENTE}").json()
    assert datos["total"] == 1
    assert datos["data"][0]["actor_id"] == ID_DOCENTE


def test_filtra_por_entidad(con_registros):
    datos = auditoria(con_registros, "?entity=assignment").json()
    assert {r["entity"] for r in datos["data"]} == {"assignment"}
    assert datos["total"] == 2


def test_filtra_por_accion(con_registros):
    datos = auditoria(con_registros, "?action=create").json()
    assert [r["entity"] for r in datos["data"]] == ["areas", "campuses"]


def test_filtra_por_fecha(con_registros):
    assert auditoria(con_registros, f"?from={HOY}&to={HOY}").json()["total"] == 4
    assert auditoria(con_registros, "?from=2000-01-01&to=2000-12-31").json()["total"] == 0


def test_filtros_combinados_y_orden_reciente_primero(con_registros):
    datos = auditoria(con_registros, f"?user_id={ID_ADMIN}&action=transition").json()
    assert [(r["from_state"], r["to_state"]) for r in datos["data"]] == [
        ("submitted", "under_review")]
    todos = auditoria(con_registros).json()["data"]
    assert [r["id"] for r in todos] == sorted((r["id"] for r in todos), reverse=True)


@pytest.mark.parametrize("consulta", ["?from=2026-02-30", "?from=2026-10-10&to=2026-10-01",
                                      "?user_id=0", "?per_page=101"])
def test_filtros_invalidos_dan_422(cliente, consulta):
    respuesta = auditoria(cliente, consulta)
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "VALIDATION_ERROR"


def test_paginacion_con_la_forma_del_contrato(con_registros):
    pagina = auditoria(con_registros, "?page=2&per_page=3").json()
    assert set(pagina) == {"page", "per_page", "total", "data"}
    assert (pagina["total"], len(pagina["data"])) == (4, 1)


# ── Permisos ──────────────────────────────────────────────────────────────

def test_docente_no_puede_consultar_la_auditoria(con_registros):
    respuesta = auditoria(con_registros, encabezados=DOCENTE)
    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "FORBIDDEN"


def test_sin_sesion_responde_401(cliente):
    respuesta = cliente.get("/api/v1/audit")
    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "UNAUTHENTICATED"


def test_openapi_incluye_la_ruta_del_contrato(cliente):
    assert "get" in cliente.get("/openapi.json").json()["paths"]["/api/v1/audit"]
