"""
Pruebas automáticas de routes.py y acciones.py.

Desde el 24/10, el inbox exige un Usuario real (vía obtener_usuario_actual
de G2), no un header X-User. En vez de armar un login completo para cada
prueba, usamos app.dependency_overrides — el mecanismo oficial de FastAPI
para reemplazar una dependencia durante pruebas, sin tocar el código real.
"""
import pytest
from fastapi.testclient import TestClient

import g4_inbox.routes as modulo_routes
from g4_inbox.main import app
from g2_api.routers.auth import obtener_usuario_actual


class RolFalso:
    def __init__(self, codigo):
        self.codigo = codigo


class UsuarioFalso:
    """No es el Usuario real de G2 (ese viene de la base) — solo necesita
    .id y .roles (lista de objetos con .codigo), que es lo que usamos."""
    def __init__(self, id, roles=()):
        self.id = id
        self.roles = [RolFalso(r) for r in roles]


def autenticar_como(id_usuario, roles=("teacher",)):
    """Reemplaza, solo durante la prueba, 'quién es el usuario actual'."""
    app.dependency_overrides[obtener_usuario_actual] = lambda: UsuarioFalso(id_usuario, roles)


cliente = TestClient(app)


@pytest.fixture(autouse=True)
def preparar_cada_prueba():
    """Reinicia los datos Y deja autenticado como el usuario 1 por defecto,
    para que las pruebas que no les importa el usuario no tengan que
    llamar autenticar_como() cada vez."""
    modulo_routes.DB[:] = modulo_routes._construir_db()
    autenticar_como(1)
    yield
    app.dependency_overrides.clear()


# ============================================================================
# SEGURIDAD — lo que exactamente reportó la prueba de integración del PM
# ============================================================================
def test_inbox_sin_token_da_401():
    """Sin override de autenticación, debe exigir el token real de verdad."""
    app.dependency_overrides.clear()  # quita el override, para simular "sin login"
    respuesta = cliente.get("/api/v1/inbox")
    assert respuesta.status_code == 401


def test_inbox_filtra_por_el_usuario_autenticado_no_por_header():
    """Aunque alguien mande X-User a mano, debe ignorarlo — el usuario
    real sale del token (acá, del override), no del header."""
    autenticar_como(1)
    respuesta_1 = cliente.get("/api/v1/inbox", headers={"X-User": "2"})  # X-User ya no existe
    datos_1 = respuesta_1.json()

    autenticar_como(2)
    respuesta_2 = cliente.get("/api/v1/inbox")
    datos_2 = respuesta_2.json()

    # Si el header X-User todavía mandara, ambas respuestas serían iguales
    assert datos_1 != datos_2


def test_acciones_no_estan_en_el_router_principal():
    """Las 6 transiciones no deben existir en routes.router — ese es
    justo el router que SÍ se monta en la raíz del proyecto."""
    rutas_del_router_principal = {r.path for r in modulo_routes.router.routes}
    assert "/api/v1/assignments/{assignment_id}/start" not in rutas_del_router_principal
    assert "/api/v1/assignments/{assignment_id}/approve" not in rutas_del_router_principal



# ============================================================================
# ACCESO A UNA ASIGNACIÓN AJENA — el hallazgo del 28/10 del PM:
# docente2 abrió GET /assignments/1 (de docente1) y recibió 200.
# ============================================================================
def test_docente_no_puede_ver_el_detalle_de_otro_docente():
    autenticar_como(2)  # docente 2
    respuesta = cliente.get("/api/v1/assignments/1")  # la 1 es de docente 1
    assert respuesta.status_code == 403


def test_el_dueno_si_puede_ver_su_detalle():
    autenticar_como(1)
    assert cliente.get("/api/v1/assignments/1").status_code == 200


def test_revisor_puede_ver_el_detalle_de_otro():
    # en los datos de ejemplo el revisor designado es el usuario 5
    autenticar_como(5, roles=("teacher", "reviewer"))
    assert cliente.get("/api/v1/assignments/1").status_code == 200


def test_revisor_no_designado_no_ve_ni_comenta():
    """Hallazgo de la integración del PM: un revisor que no es el de la tarea no la ve."""
    autenticar_como(6, roles=("teacher", "reviewer"))
    assert cliente.get("/api/v1/assignments/1").status_code == 403
    assert cliente.post("/api/v1/assignments/1/comments", json={"text": "x"}).status_code == 403


def test_coordinador_puede_ver_el_detalle_de_otro():
    autenticar_como(2, roles=("coordinator",))
    assert cliente.get("/api/v1/assignments/1").status_code == 200


def test_docente_no_puede_leer_ni_escribir_comentarios_ajenos():
    autenticar_como(2)
    assert cliente.get("/api/v1/assignments/1/comments").status_code == 403
    assert cliente.post("/api/v1/assignments/1/comments", json={"text": "hola"}).status_code == 403


def test_docente_no_puede_tocar_borrador_ni_archivos_ajenos():
    autenticar_como(2)
    assert cliente.put("/api/v1/assignments/1/submission-draft", json={"comment": "x"}).status_code == 403
    assert cliente.post("/api/v1/assignments/1/files",
                         json={"file_id": "f-x", "name": "x.pdf"}).status_code == 403


def test_revisor_puede_comentar_pero_no_tocar_el_borrador_del_docente():
    autenticar_como(5, roles=("teacher", "reviewer"))
    assert cliente.post("/api/v1/assignments/1/comments", json={"text": "observación"}).status_code == 200
    assert cliente.put("/api/v1/assignments/1/submission-draft", json={"comment": "x"}).status_code == 403


def test_admin_puede_ver_y_comentar_pero_no_tocar_la_entrega():
    # el admin entra con un id que no es el del dueño (docente 1)
    autenticar_como(99, roles=("admin",))
    assert cliente.get("/api/v1/assignments/1").status_code == 200
    assert cliente.post("/api/v1/assignments/1/comments", json={"text": "nota"}).status_code == 200
    assert cliente.put("/api/v1/assignments/1/submission-draft", json={"comment": "x"}).status_code == 403
    assert cliente.post("/api/v1/assignments/1/files",
                         json={"file_id": "f-x", "name": "x.pdf"}).status_code == 403


def test_auditor_solo_puede_ver():
    autenticar_como(99, roles=("auditor",))
    assert cliente.get("/api/v1/assignments/1").status_code == 200
    assert cliente.get("/api/v1/assignments/1/comments").status_code == 200
    assert cliente.post("/api/v1/assignments/1/comments", json={"text": "nota"}).status_code == 403
    assert cliente.put("/api/v1/assignments/1/submission-draft", json={"comment": "x"}).status_code == 403
    assert cliente.post("/api/v1/assignments/1/files",
                         json={"file_id": "f-x", "name": "x.pdf"}).status_code == 403


def test_un_docente_cualquiera_sigue_sin_acceso():
    autenticar_como(99, roles=("teacher",))
    assert cliente.get("/api/v1/assignments/1").status_code == 403


# ============================================================================
# DETALLE
# ============================================================================
def test_detalle_de_tarea_existente_devuelve_200():
    respuesta = cliente.get("/api/v1/assignments/1")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["id"] == 1
    assert "allowed_actions" in cuerpo


def test_detalle_de_tarea_inexistente_devuelve_404():
    respuesta = cliente.get("/api/v1/assignments/9999")
    assert respuesta.status_code == 404


def test_detalle_sin_token_da_401():
    app.dependency_overrides.clear()
    respuesta = cliente.get("/api/v1/assignments/1")
    assert respuesta.status_code == 401


# ============================================================================
# BORRADOR
# ============================================================================
def test_guardar_borrador_no_cambia_el_estado():
    antes = cliente.get("/api/v1/assignments/2").json()["status"]
    respuesta = cliente.put(
        "/api/v1/assignments/2/submission-draft",
        json={"comment": "borrador de prueba"},
    )
    despues = cliente.get("/api/v1/assignments/2").json()["status"]
    assert respuesta.status_code == 200
    assert respuesta.json()["draft_comment"] == "borrador de prueba"
    assert antes == despues


def test_guardar_borrador_en_tarea_inexistente_devuelve_404():
    respuesta = cliente.put("/api/v1/assignments/9999/submission-draft", json={})
    assert respuesta.status_code == 404


# ============================================================================
# COMENTARIOS
# ============================================================================
def test_crear_y_listar_comentario():
    respuesta = cliente.post(
        "/api/v1/assignments/1/comments", json={"text": "comentario de prueba"}
    )
    assert respuesta.status_code == 200
    listado = cliente.get("/api/v1/assignments/1/comments").json()
    assert any(c["text"] == "comentario de prueba" for c in listado)


def test_comentario_sin_texto_es_rechazado():
    respuesta = cliente.post("/api/v1/assignments/1/comments", json={})
    assert respuesta.status_code == 422


# ============================================================================
# ARCHIVOS
# ============================================================================
def test_vincular_archivo():
    respuesta = cliente.post(
        "/api/v1/assignments/1/files",
        json={"file_id": "f-test-1", "name": "evidencia.pdf"},
    )
    assert respuesta.status_code == 200
    assert {"file_id": "f-test-1", "name": "evidencia.pdf"} in respuesta.json()["files"]


# ============================================================================
# TRANSICIONES — siguen probándose, pero ahora contra acciones_router,
# montado solo en main.py (pruebas locales), no en routes.router.
# ============================================================================
@pytest.fixture
def tarea_assigned():
    inbox = cliente.get("/api/v1/inbox").json()["data"]
    for t in inbox:
        if t["status"] == "assigned":
            return t["id"]
    pytest.skip("No hay ninguna tarea en 'assigned' para probar el ciclo")


def test_iniciar_tarea_assigned_pasa_a_in_progress(tarea_assigned):
    respuesta = cliente.post(
        f"/api/v1/assignments/{tarea_assigned}/start", headers={"X-Role": "docente"}
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "in_progress"


def test_transicion_invalida_devuelve_409(tarea_assigned):
    respuesta = cliente.post(
        f"/api/v1/assignments/{tarea_assigned}/approve", headers={"X-Role": "revisor"}
    )
    assert respuesta.status_code == 409


def test_transicion_con_rol_incorrecto_devuelve_403(tarea_assigned):
    respuesta = cliente.post(
        f"/api/v1/assignments/{tarea_assigned}/start", headers={"X-Role": "revisor"}
    )
    assert respuesta.status_code == 403


def test_entregar_sin_archivo_devuelve_422(tarea_assigned):
    cliente.post(f"/api/v1/assignments/{tarea_assigned}/start", headers={"X-Role": "docente"})
    respuesta = cliente.post(
        f"/api/v1/assignments/{tarea_assigned}/submit", headers={"X-Role": "docente"}
    )
    assert respuesta.status_code == 422


def test_devolver_sin_observacion_devuelve_422(tarea_assigned):
    cliente.post(f"/api/v1/assignments/{tarea_assigned}/start", headers={"X-Role": "docente"})
    cliente.post(
        f"/api/v1/assignments/{tarea_assigned}/files",
        json={"file_id": "f-test-2", "name": "ev.pdf"},
    )
    cliente.post(f"/api/v1/assignments/{tarea_assigned}/submit", headers={"X-Role": "docente"})
    cliente.post(f"/api/v1/assignments/{tarea_assigned}/review", headers={"X-Role": "revisor"})
    respuesta = cliente.post(
        f"/api/v1/assignments/{tarea_assigned}/return",
        headers={"X-Role": "revisor"},
        json={"comment": ""},
    )
    assert respuesta.status_code == 422


def test_ciclo_completo_hasta_aprobada(tarea_assigned):
    t = tarea_assigned
    assert cliente.post(f"/api/v1/assignments/{t}/start", headers={"X-Role": "docente"}).status_code == 200
    cliente.post(f"/api/v1/assignments/{t}/files", json={"file_id": "f-test-3", "name": "ev.pdf"})
    assert cliente.post(f"/api/v1/assignments/{t}/submit", headers={"X-Role": "docente"}).status_code == 200
    assert cliente.post(f"/api/v1/assignments/{t}/review", headers={"X-Role": "revisor"}).status_code == 200
    respuesta = cliente.post(f"/api/v1/assignments/{t}/approve", headers={"X-Role": "revisor"})
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "approved"


def test_el_detalle_dice_si_quien_mira_es_el_docente_o_el_revisor():
    """La pantalla usa esto para no mostrarle al docente el botón de revisar."""
    autenticar_como(1)   # dueño de la asignación 1
    assert cliente.get("/api/v1/assignments/1").json()["viewer"] == {"is_assignee": True, "is_reviewer": False}
    autenticar_como(5, roles=("teacher", "reviewer"))   # revisor designado
    assert cliente.get("/api/v1/assignments/1").json()["viewer"] == {"is_assignee": False, "is_reviewer": True}
    autenticar_como(9, roles=("auditor",))
    assert cliente.get("/api/v1/assignments/1").json()["viewer"] == {"is_assignee": False, "is_reviewer": False}


def test_el_detalle_de_una_devuelta_trae_la_observacion():
    autenticar_como(1)
    d = cliente.get("/api/v1/assignments/3").json()
    if d["status"] != "returned":
        pytest.skip("En los datos de ejemplo la asignación 3 no está devuelta")
    assert d["last_return"]["comment"] == "El monto no coincide. Verificar y reenviar."
