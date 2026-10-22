"""Pruebas de notificaciones: escenarios G6-04 a G6-13 y G6-18."""

import pytest
from fastapi.testclient import TestClient

from g6_admin.app_demo import crear_app_demo
from g6_admin.errores import ErrorApi
from g6_admin.notificaciones import (EVENTOS, RepositorioNotificacionesEnMemoria,
                                     ServicioNotificaciones)
from g6_admin.seguridad import USUARIOS_DEMO

ADMIN = {"X-Demo-Role": "admin"}
DOCENTE = {"X-Demo-Role": "teacher"}
ID_ADMIN = USUARIOS_DEMO["admin"].id
ID_DOCENTE = USUARIOS_DEMO["teacher"].id

DATOS = {"task_title": "Sílabo", "due_date": "2026-11-15", "comment": "Falta la bibliografía.",
         "program_name": "Programación Web"}


def evento(nombre, recipients=(ID_DOCENTE,), evento_id=None, **datos):
    return {"id": evento_id or f"{nombre}-1", "name": nombre, "recipients": list(recipients),
            "data": {c: DATOS[c] for c in EVENTOS[nombre].campos} | datos}


@pytest.fixture
def servicio() -> ServicioNotificaciones:
    return ServicioNotificaciones(RepositorioNotificacionesEnMemoria())


@pytest.fixture
def app():
    return crear_app_demo(auth_demo=True, datos_ejemplo=False)


@pytest.fixture
def cliente(app) -> TestClient:
    return TestClient(app)


def publicar(app, datos_evento):
    return app.state.g6_notificaciones.procesar_evento(datos_evento)


def mis_notificaciones(cliente, encabezados=DOCENTE, consulta=""):
    return cliente.get(f"/api/v1/notifications{consulta}", headers=encabezados).json()


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
def test_cada_evento_notifica_a_sus_destinatarios(app, cliente, nombre, destinatarios, texto):
    creadas = publicar(app, evento(nombre, destinatarios))

    assert len(creadas) == len(destinatarios)
    for encabezados, usuario_id in ((DOCENTE, ID_DOCENTE), (ADMIN, ID_ADMIN)):
        recibidas = mis_notificaciones(cliente, encabezados)["data"]
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

def test_mismo_evento_dos_veces_no_duplica(servicio):
    datos_evento = evento("assignment.approved", [ID_DOCENTE, ID_ADMIN])
    assert len(servicio.procesar_evento(datos_evento)) == 2
    assert servicio.procesar_evento(datos_evento) == []
    assert servicio.listar(USUARIOS_DEMO["teacher"])["total"] == 1


def test_destinatario_repetido_recibe_una_sola(servicio):
    servicio.procesar_evento(evento("task.published", [ID_DOCENTE, ID_DOCENTE]))
    assert servicio.listar(USUARIOS_DEMO["teacher"])["total"] == 1


def test_eventos_distintos_si_se_guardan(servicio):
    servicio.procesar_evento(evento("task.published", evento_id="t-1"))
    servicio.procesar_evento(evento("task.published", evento_id="t-2"))
    assert servicio.listar(USUARIOS_DEMO["teacher"])["total"] == 2


# ── G6-18: un evento inválido no deja nada a medias ───────────────────────

@pytest.mark.parametrize("cambio, campo", [
    ({"name": "task.unknown"}, "name"),
    ({"id": ""}, "id"),
    ({"recipients": []}, "recipients"),
    ({"recipients": [ID_DOCENTE, "2"]}, "recipients"),
    ({"recipients": [True]}, "recipients"),
    ({"data": {"task_title": "Sílabo"}}, "data.comment"),
    ({"data": {"task_title": "  ", "comment": "x"}}, "data.task_title"),
    ({"data": {"task_title": "x" * 501, "comment": "x"}}, "data.task_title"),
])
def test_evento_invalido_da_422_y_no_guarda_nada(servicio, cambio, campo):
    datos_evento = evento("assignment.returned", [ID_DOCENTE, ID_ADMIN]) | cambio
    with pytest.raises(ErrorApi) as error:
        servicio.procesar_evento(datos_evento)
    assert error.value.estado_http == 422
    assert campo in error.value.detalles
    for usuario in USUARIOS_DEMO.values():
        assert servicio.listar(usuario)["total"] == 0


def test_evento_que_no_es_objeto(servicio):
    with pytest.raises(ErrorApi):
        servicio.procesar_evento(["task.published"])


# ── G6-12 y G6-13: marcar como leída solo afecta al destinatario ──────────

def test_marcar_como_leida_solo_cambia_esa(app, cliente):
    publicar(app, evento("task.published", evento_id="t-1"))
    publicar(app, evento("task.cancelled", [ID_DOCENTE, ID_ADMIN], evento_id="t-2"))
    cancelada = mis_notificaciones(cliente)["data"][0]

    respuesta = cliente.patch(f"/api/v1/notifications/{cancelada['id']}/read", headers=DOCENTE)

    assert respuesta.status_code == 200
    assert respuesta.json()["is_read"] is True
    assert respuesta.json()["read_at"] is not None
    estados = {n["event"]: n["is_read"] for n in mis_notificaciones(cliente)["data"]}
    assert estados == {"task.cancelled": True, "task.published": False}
    # La copia del administrador sigue sin leer.
    assert mis_notificaciones(cliente, ADMIN)["data"][0]["is_read"] is False


def test_marcar_dos_veces_conserva_la_primera_fecha(app, cliente):
    creada = publicar(app, evento("task.published"))[0]
    ruta = f"/api/v1/notifications/{creada['id']}/read"
    primera = cliente.patch(ruta, headers=DOCENTE).json()["read_at"]
    assert cliente.patch(ruta, headers=DOCENTE).json()["read_at"] == primera


def test_no_puede_marcar_la_de_otra_persona(app, cliente):
    ajena = publicar(app, evento("assignment.submitted", [ID_ADMIN]))[0]

    respuesta = cliente.patch(f"/api/v1/notifications/{ajena['id']}/read", headers=DOCENTE)

    # 404 igual que una inexistente: no revela que la notificación existe.
    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "NOT_FOUND"
    assert mis_notificaciones(cliente, ADMIN)["data"][0]["is_read"] is False


def test_marcar_una_inexistente_da_404(cliente):
    assert cliente.patch("/api/v1/notifications/999/read", headers=DOCENTE).status_code == 404


# ── Listado y sesión ──────────────────────────────────────────────────────

def test_lista_las_mas_recientes_primero_y_filtra_no_leidas(app, cliente):
    for numero in range(3):
        publicar(app, evento("task.published", evento_id=f"t-{numero}",
                             task_title=f"Tarea {numero}"))
    primera = mis_notificaciones(cliente)["data"][-1]
    cliente.patch(f"/api/v1/notifications/{primera['id']}/read", headers=DOCENTE)

    todas = mis_notificaciones(cliente)
    assert [n["message"].split("«")[1].split("»")[0] for n in todas["data"]] == [
        "Tarea 2", "Tarea 1", "Tarea 0"]
    assert mis_notificaciones(cliente, consulta="?unread=true")["total"] == 2


def test_paginacion_con_la_forma_del_contrato(app, cliente):
    for numero in range(5):
        publicar(app, evento("task.published", evento_id=f"t-{numero}"))
    pagina = mis_notificaciones(cliente, consulta="?page=2&per_page=2")
    assert set(pagina) == {"page", "per_page", "total", "data"}
    assert (pagina["page"], pagina["total"], len(pagina["data"])) == (2, 5, 2)


@pytest.mark.parametrize("metodo, ruta", [("get", "/api/v1/notifications"),
                                          ("patch", "/api/v1/notifications/1/read")])
def test_sin_sesion_responde_401(cliente, metodo, ruta):
    respuesta = getattr(cliente, metodo)(ruta)
    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "UNAUTHENTICATED"


def test_la_demo_trae_notificaciones_de_ejemplo():
    cliente = TestClient(crear_app_demo(auth_demo=True, datos_ejemplo=True))
    assert mis_notificaciones(cliente)["total"] == 3
    assert mis_notificaciones(cliente, ADMIN)["total"] == 1


def test_openapi_incluye_las_rutas_del_contrato(cliente):
    rutas = cliente.get("/openapi.json").json()["paths"]
    assert "get" in rutas["/api/v1/notifications"]
    assert "patch" in rutas["/api/v1/notifications/{notificacion_id}/read"]
