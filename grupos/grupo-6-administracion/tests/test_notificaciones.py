"""Pruebas de notificaciones: escenarios G6-04 a G6-13 y G6-18."""

import pytest
from fastapi import HTTPException

from conftest import ADMINISTRACION, DOCENTE
from g6_admin.notificaciones import EVENTOS

ID_ADMIN = ADMINISTRACION.id
ID_DOCENTE = DOCENTE.id

DATOS = {"task_title": "Sílabo", "due_date": "2026-11-15", "comment": "Falta la bibliografía.",
         "program_name": "Programación Web"}


def evento(nombre, recipients=(ID_DOCENTE,), evento_id=None, **datos):
    return {"id": evento_id or f"{nombre}-1", "name": nombre, "recipients": list(recipients),
            "data": {c: DATOS[c] for c in EVENTOS[nombre].campos} | datos}


def mis_notificaciones(cliente, consulta=""):
    return cliente.get(f"/api/v1/notifications{consulta}").json()


def detalle(error: HTTPException) -> set[str]:
    return {d["field"] for d in error.detail["details"]["items"]}


# ── G6-04 a G6-10: cada evento llega a sus destinatarios ──────────────────

@pytest.mark.parametrize("nombre, destinatarios, texto", [
    ("task.published", [ID_DOCENTE], "2026-11-15"),
    ("assignment.due_soon", [ID_DOCENTE], "vence el 2026-11-15"),
    ("assignment.submitted", [ID_ADMIN], "lista para revisión"),
    ("assignment.returned", [ID_DOCENTE], "Observación: Falta la bibliografía."),
    ("assignment.approved", [ID_DOCENTE, ID_ADMIN], "aprobada"),
    ("program.authorized", [ID_DOCENTE, ID_ADMIN], "Programación Web"),
    ("task.cancelled", [ID_DOCENTE, ID_ADMIN], "cancelada"),
])
def test_cada_evento_notifica_a_sus_destinatarios(notificaciones, admin, docente,
                                                  nombre, destinatarios, texto):
    creadas = notificaciones.procesar_evento(evento(nombre, destinatarios))

    assert len(creadas) == len(destinatarios)
    for cliente, usuario_id in ((docente, ID_DOCENTE), (admin, ID_ADMIN)):
        recibidas = mis_notificaciones(cliente)["data"]
        if usuario_id in destinatarios:
            assert [n["event"] for n in recibidas] == [nombre]
            assert texto in recibidas[0]["message"]
            assert recibidas[0]["is_read"] is False
        else:
            assert recibidas == []


def test_estan_los_siete_eventos_oficiales():
    assert set(EVENTOS) == {"task.published", "assignment.due_soon", "assignment.submitted",
                            "assignment.returned", "assignment.approved",
                            "program.authorized", "task.cancelled"}


# ── G6-11: sin duplicados ─────────────────────────────────────────────────

def test_mismo_evento_dos_veces_no_duplica(notificaciones):
    datos_evento = evento("assignment.approved", [ID_DOCENTE, ID_ADMIN])
    assert len(notificaciones.procesar_evento(datos_evento)) == 2
    assert notificaciones.procesar_evento(datos_evento) == []
    assert len(notificaciones.listar(ID_DOCENTE)) == 1


def test_destinatario_repetido_recibe_una_sola(notificaciones):
    notificaciones.procesar_evento(evento("task.published", [ID_DOCENTE, ID_DOCENTE]))
    assert len(notificaciones.listar(ID_DOCENTE)) == 1


def test_eventos_distintos_si_se_guardan(notificaciones):
    notificaciones.procesar_evento(evento("task.published", evento_id="t-1"))
    notificaciones.procesar_evento(evento("task.published", evento_id="t-2"))
    assert len(notificaciones.listar(ID_DOCENTE)) == 2


# ── G6-18: un evento inválido no deja nada a medias ───────────────────────

@pytest.mark.parametrize("cambio, campo", [
    ({"name": "task.unknown"}, "name"),
    ({"name": ["task.published"]}, "name"),
    ({"id": ""}, "id"),
    ({"recipients": []}, "recipients"),
    ({"recipients": [ID_DOCENTE, "2"]}, "recipients"),
    ({"recipients": [True]}, "recipients"),
    ({"data": {"task_title": "Sílabo"}}, "data.comment"),
    ({"data": {"task_title": "  ", "comment": "x"}}, "data.task_title"),
    ({"data": {"task_title": "x" * 501, "comment": "x"}}, "data.task_title"),
])
def test_evento_invalido_da_422_y_no_guarda_nada(notificaciones, cambio, campo):
    datos_evento = evento("assignment.returned", [ID_DOCENTE, ID_ADMIN]) | cambio
    with pytest.raises(HTTPException) as error:
        notificaciones.procesar_evento(datos_evento)
    assert error.value.status_code == 422
    assert campo in detalle(error.value)
    assert notificaciones.listar(ID_DOCENTE) == notificaciones.listar(ID_ADMIN) == []


def test_evento_que_no_es_objeto(notificaciones):
    with pytest.raises(HTTPException):
        notificaciones.procesar_evento(["task.published"])


# ── G6-12 y G6-13: marcar como leída solo afecta al destinatario ──────────

def test_marcar_como_leida_solo_cambia_esa(notificaciones, admin, docente):
    notificaciones.procesar_evento(evento("task.published", evento_id="t-1"))
    notificaciones.procesar_evento(evento("task.cancelled", [ID_DOCENTE, ID_ADMIN],
                                          evento_id="t-2"))
    cancelada = mis_notificaciones(docente)["data"][0]

    respuesta = docente.patch(f"/api/v1/notifications/{cancelada['id']}/read")

    assert respuesta.status_code == 200
    assert respuesta.json()["is_read"] is True
    assert respuesta.json()["read_at"] is not None
    estados = {n["event"]: n["is_read"] for n in mis_notificaciones(docente)["data"]}
    assert estados == {"task.cancelled": True, "task.published": False}
    # La copia de administración sigue sin leer.
    assert mis_notificaciones(admin)["data"][0]["is_read"] is False


def test_marcar_dos_veces_conserva_la_primera_fecha(notificaciones, docente):
    creada = notificaciones.procesar_evento(evento("task.published"))[0]
    ruta = f"/api/v1/notifications/{creada['id']}/read"
    primera = docente.patch(ruta).json()["read_at"]
    assert docente.patch(ruta).json()["read_at"] == primera


def test_no_puede_marcar_la_de_otra_persona(notificaciones, admin, docente):
    ajena = notificaciones.procesar_evento(evento("assignment.submitted", [ID_ADMIN]))[0]

    respuesta = docente.patch(f"/api/v1/notifications/{ajena['id']}/read")

    # 404 igual que una inexistente: no revela que la notificación existe.
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "NOT_FOUND"
    assert mis_notificaciones(admin)["data"][0]["is_read"] is False


def test_marcar_una_inexistente_da_404(docente):
    assert docente.patch("/api/v1/notifications/999/read").status_code == 404


# ── Listado y sesión ──────────────────────────────────────────────────────

def test_lista_las_mas_recientes_primero_y_filtra_no_leidas(notificaciones, docente):
    for numero in range(3):
        notificaciones.procesar_evento(evento("task.published", evento_id=f"t-{numero}",
                                              task_title=f"Tarea {numero}"))
    primera = mis_notificaciones(docente)["data"][-1]
    docente.patch(f"/api/v1/notifications/{primera['id']}/read")

    todas = mis_notificaciones(docente)
    assert [n["message"].split("«")[1].split("»")[0] for n in todas["data"]] == [
        "Tarea 2", "Tarea 1", "Tarea 0"]
    assert mis_notificaciones(docente, "?unread=true")["total"] == 2


def test_paginacion_con_la_forma_del_contrato(notificaciones, docente):
    for numero in range(5):
        notificaciones.procesar_evento(evento("task.published", evento_id=f"t-{numero}"))
    pagina = mis_notificaciones(docente, "?page=2&per_page=2")
    assert set(pagina) == {"page", "per_page", "total", "data"}
    assert (pagina["page"], pagina["total"], len(pagina["data"])) == (2, 5, 2)


@pytest.mark.parametrize("metodo, ruta", [("get", "/api/v1/notifications"),
                                          ("patch", "/api/v1/notifications/1/read")])
def test_sin_sesion_responde_401(sin_sesion, metodo, ruta):
    respuesta = getattr(sin_sesion, metodo)(ruta)
    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "UNAUTHORIZED"


def test_openapi_incluye_las_rutas_del_contrato(admin):
    rutas = admin.get("/openapi.json").json()["paths"]
    assert "get" in rutas["/api/v1/notifications"]
    assert "patch" in rutas["/api/v1/notifications/{notificacion_id}/read"]
