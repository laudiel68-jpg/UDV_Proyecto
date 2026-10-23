"""Pruebas de auditoría: escenarios G6-14, G6-15 y G6-30 a G6-33."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from conftest import ADMINISTRACION, DOCENTE

ID_ADMIN = ADMINISTRACION.id
ID_DOCENTE = DOCENTE.id
HOY = datetime.now(timezone.utc).date().isoformat()  # La auditoría guarda en UTC

TRANSICION = {"actor_id": ID_DOCENTE, "entidad": "tarea_destinatario", "entidad_id": 58,
              "estado_anterior": "in_progress", "estado_nuevo": "submitted",
              "comentario": "Entrego la planificación."}


def consultar(cliente, consulta=""):
    return cliente.get(f"/api/v1/audit{consulta}")


def detalle(error: HTTPException) -> set[str]:
    return {d["field"] for d in error.detail["details"]["items"]}


def transicion(auditoria, **datos):
    # Quien llama (G3 o G5) hace el commit junto con su propio cambio.
    auditoria.registrar_transicion(**datos)
    auditoria.repositorio.sesion.commit()


# ── G6-14: una acción auditada queda registrada ───────────────────────────

def test_crear_un_registro_de_catalogo_queda_auditado(admin):
    creado = admin.post("/api/v1/campuses", json={"code": "norte", "name": "Sede Norte"}).json()

    registros = consultar(admin).json()["data"]

    assert len(registros) == 1
    registro = registros[0]
    assert (registro["actor_id"], registro["action"]) == (ID_ADMIN, "insert")
    # La entidad es la tabla del G1, igual que en sus triggers de auditoría.
    assert (registro["entity"], registro["entity_id"]) == ("sede", creado["id"])
    assert registro["changes"] == {"despues": {"code": "NORTE", "name": "Sede Norte",
                                               "is_active": True}}
    assert registro["created_at"].startswith(HOY)


def test_modificar_un_registro_de_catalogo_queda_auditado(admin, docente):
    creado = admin.post("/api/v1/areas", json={"code": "SIS", "name": "Sistemas"}).json()
    admin.patch(f"/api/v1/areas/{creado['id']}", json={"is_active": False})
    # Un cambio rechazado (docente) no se audita.
    docente.patch(f"/api/v1/areas/{creado['id']}", json={"name": "Otra"})

    datos = consultar(admin).json()

    assert datos["total"] == 2
    ultimo = datos["data"][0]
    assert (ultimo["action"], ultimo["entity"], ultimo["entity_id"]) == (
        "update", "area", creado["id"])
    assert ultimo["changes"] == {"antes": {"is_active": True}, "despues": {"is_active": False}}


def test_una_operacion_rechazada_no_deja_registro(admin, docente):
    docente.post("/api/v1/campuses", json={"code": "NORTE", "name": "Sede"})
    admin.post("/api/v1/campuses", json={"code": "x"})
    assert consultar(admin).json()["total"] == 0


def test_registrar_accion_valida_los_datos(auditoria):
    with pytest.raises(HTTPException) as error:
        auditoria.registrar(actor_id=0, accion="", entidad=None, entidad_id="5")
    assert detalle(error.value) == {"actor_id", "action", "entity", "entity_id"}


def test_la_auditoria_no_se_puede_editar_ni_borrar(auditoria):
    registro = auditoria.registrar(actor_id=1, accion="insert", entidad="area", entidad_id=1)
    # El repositorio no ofrece métodos para cambiar ni borrar. En MySQL,
    # además, los triggers del G1 rechazan UPDATE y DELETE (ver
    # tests/integracion/test_mysql_g1.py).
    assert not any(hasattr(auditoria.repositorio, m)
                   for m in ("modificar", "actualizar", "borrar", "eliminar"))
    # Cambiar el diccionario devuelto no altera lo guardado.
    registro["changes"]["code"] = "OTRO"
    assert auditoria.consultar()[1][0]["changes"] == {}


# ── G6-15: una transición guarda actor, fecha, estados y comentario ───────

def test_transicion_registra_lo_que_pide_el_contrato(auditoria, admin):
    transicion(auditoria, **TRANSICION)

    registro = consultar(admin).json()["data"][0]

    assert registro["action"] == "transition"
    assert registro["actor_id"] == ID_DOCENTE
    assert registro["created_at"].startswith(HOY)
    assert (registro["from_state"], registro["to_state"]) == ("in_progress", "submitted")
    assert registro["comment"] == "Entrego la planificación."


def test_transicion_de_programa_usa_los_estados_de_programa(auditoria):
    auditoria.registrar_transicion(actor_id=ID_ADMIN, entidad="programa_version",
                                   entidad_id=3, estado_anterior="approved",
                                   estado_nuevo="authorized")
    with pytest.raises(HTTPException) as error:
        # "closed" es de tareas, no de programas.
        auditoria.registrar_transicion(actor_id=ID_ADMIN, entidad="programa_version",
                                       entidad_id=3, estado_anterior="authorized",
                                       estado_nuevo="closed")
    assert "to_state" in detalle(error.value)


@pytest.mark.parametrize("cambio, campo", [
    ({"estado_anterior": "enviado"}, "from_state"),
    ({"estado_nuevo": "SUBMITTED"}, "to_state"),
    ({"estado_nuevo": "in_progress"}, "to_state"),
    ({"entidad": "sede"}, "entity"),
    ({"entidad": ["tarea"]}, "entity"),
    ({"comentario": None}, "comment"),
    ({"comentario": "x" * 1001}, "comment"),
    ({"actor_id": True}, "actor_id"),
])
def test_transicion_invalida_da_422_y_no_se_guarda(auditoria, cambio, campo):
    with pytest.raises(HTTPException) as error:
        auditoria.registrar_transicion(**(TRANSICION | cambio))
    assert error.value.status_code == 422
    assert campo in detalle(error.value)
    assert auditoria.consultar()[0] == 0


def test_transicion_no_entra_por_registrar(auditoria):
    with pytest.raises(HTTPException):
        auditoria.registrar(actor_id=1, accion="transition", entidad="tarea", entidad_id=1)


# ── G6-30 a G6-33: filtros por usuario, fecha, entidad y acción ───────────

@pytest.fixture
def con_registros(auditoria, admin):
    admin.post("/api/v1/campuses", json={"code": "NORTE", "name": "Sede Norte"})
    admin.post("/api/v1/areas", json={"code": "SIS", "name": "Sistemas"})
    transicion(auditoria, **TRANSICION)
    transicion(auditoria, **TRANSICION | {
        "actor_id": ID_ADMIN, "estado_anterior": "submitted", "estado_nuevo": "under_review"})
    return admin


def test_filtra_por_usuario(con_registros):
    datos = consultar(con_registros, f"?user_id={ID_DOCENTE}").json()
    assert datos["total"] == 1
    assert datos["data"][0]["actor_id"] == ID_DOCENTE


def test_filtra_por_entidad(con_registros):
    datos = consultar(con_registros, "?entity=tarea_destinatario").json()
    assert {r["entity"] for r in datos["data"]} == {"tarea_destinatario"}
    assert datos["total"] == 2


def test_filtra_por_accion(con_registros):
    datos = consultar(con_registros, "?action=insert").json()
    assert [r["entity"] for r in datos["data"]] == ["area", "sede"]


def test_filtra_por_fecha(con_registros):
    assert consultar(con_registros, f"?from={HOY}&to={HOY}").json()["total"] == 4
    assert consultar(con_registros, "?from=2000-01-01&to=2000-12-31").json()["total"] == 0


def test_filtros_combinados_y_orden_reciente_primero(con_registros):
    datos = consultar(con_registros, f"?user_id={ID_ADMIN}&action=transition").json()
    assert [(r["from_state"], r["to_state"]) for r in datos["data"]] == [
        ("submitted", "under_review")]
    todos = consultar(con_registros).json()["data"]
    assert [r["id"] for r in todos] == sorted((r["id"] for r in todos), reverse=True)


@pytest.mark.parametrize("consulta", ["?from=2026-02-30", "?from=2026-10-10&to=2026-10-01",
                                      "?user_id=0", "?per_page=101"])
def test_filtros_invalidos_dan_422(admin, consulta):
    respuesta = consultar(admin, consulta)
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["code"] == "VALIDATION_ERROR"


def test_paginacion_con_la_forma_del_contrato(con_registros):
    pagina = consultar(con_registros, "?page=2&per_page=3").json()
    assert set(pagina) == {"page", "per_page", "total", "data"}
    assert (pagina["total"], len(pagina["data"])) == (4, 1)


# ── Permisos ──────────────────────────────────────────────────────────────

def test_docente_no_puede_consultar_la_auditoria(con_registros, docente):
    respuesta = consultar(docente)
    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "FORBIDDEN"


def test_sin_sesion_responde_401(sin_sesion):
    respuesta = consultar(sin_sesion)
    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "UNAUTHORIZED"


def test_openapi_incluye_la_ruta_del_contrato(admin):
    assert "get" in admin.get("/openapi.json").json()["paths"]["/api/v1/audit"]
