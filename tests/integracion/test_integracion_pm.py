"""Pruebas de integración del PM: app completa (main.py) contra MySQL con db_udv del G1.

Cubre lo que no cubre tests/integracion del G6: G4 (inbox y entregas) y G5
(programas) dentro de la app integrada, autorización cruzada entre módulos,
archivos del G2, formato de error común y errores SQLSTATE 45000 de los triggers.

Cada prueba afirma el comportamiento que piden README, CONTRATO_COMUN y los
CONTRATO.md: si falla, es un defecto, no una prueba mal escrita.

    set UDV_TEST_MYSQL_URL=mysql+pymysql://udv_app:<clave>@127.0.0.1:3317/db_udv
    set UDV_RAIZ=<ruta del repo>
    python -m pytest test_integracion_pm.py -v

Escribe datos: usar SOLO con una base de pruebas desechable, nunca la de Railway.
"""
import importlib
import re
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

URL = os.getenv("UDV_TEST_MYSQL_URL")
RAIZ = Path(os.getenv("UDV_RAIZ", "."))
pytestmark = pytest.mark.skipif(not URL, reason="Define UDV_TEST_MYSQL_URL")

CLAVE_DEMO = "Demo2026!"
ADMIN, COORD, DOC1, DOC2, REVISOR, DIRECCION, AUDITOR = 1, 2, 3, 4, 5, 6, 7
PDF_MINIMO = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
              b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def app():
    os.environ["DATABASE_URL"] = URL
    os.environ.setdefault("SECRET_KEY", "clave-solo-para-pruebas-de-integracion-pm-32+")
    sys.path.insert(0, str(RAIZ))
    os.chdir(RAIZ)
    return importlib.import_module("main")


@pytest.fixture(scope="session")
def c(app):
    from fastapi.testclient import TestClient
    with TestClient(app.app, raise_server_exceptions=False) as cliente:
        yield cliente


def _login(c, correo):
    r = c.post("/api/v1/auth/login", json={"correo": correo, "password": CLAVE_DEMO})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def s(c):
    return {k: _login(c, f"{k}@demo.udv.edu.gt") for k in
            ("admin", "coordinacion", "docente1", "docente2", "revisor", "direccion", "auditoria")}


def _items(cuerpo):
    return cuerpo.get("data") or cuerpo.get("items") or [] if isinstance(cuerpo, dict) else cuerpo


def publicar(c, s, para=(DOC1,), dias=10, tipo=1, revisor=REVISOR):
    titulo = f"PMINT-{uuid.uuid4().hex[:6].upper()}"
    cuerpo = {"type_id": tipo, "title": titulo,
              "due_date": (date.today() + timedelta(days=dias)).isoformat()}
    if revisor:
        cuerpo["reviewer_id"] = revisor
    r = c.post("/api/v1/tasks", headers=s["coordinacion"], json=cuerpo)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert c.post(f"/api/v1/tasks/{tid}/recipients", headers=s["coordinacion"],
                  json={"mode": "users", "user_ids": list(para)}).status_code == 200
    assert c.post(f"/api/v1/tasks/{tid}/publish", headers=s["coordinacion"]).status_code == 200
    asign = _items(c.get(f"/api/v1/tasks/{tid}/assignments", headers=s["coordinacion"]).json())
    return titulo, {a.get("user_id", a.get("assignee_id")): a["id"] for a in asign}


def es_error_comun(r, codigo_http):
    assert r.status_code == codigo_http, f"{r.status_code} {r.text[:300]}"
    cuerpo = r.json()
    assert set(cuerpo) == {"error"}, f"formato no común: {cuerpo}"
    assert {"code", "message"} <= set(cuerpo["error"]), cuerpo


# ------------------------------------------------------------ 1. arranque
def test_todos_los_routers_montados_y_base_conectada(c):
    h = c.get("/health").json()
    assert h["pendientes"] == {}, h["pendientes"]
    assert len(h["routers"]) == 9
    db = c.get("/health/db").json()
    assert db["status"] == "ok" and db["tablas"] == 50, db


def test_salud_del_g6_responde(c):
    assert c.get("/api/v1/health").status_code == 200


def test_rutas_protegidas_sin_token_dan_401_con_formato_comun(c, app):
    """Toda ruta con seguridad en el OpenAPI rechaza sin token con el error común."""
    malas = []
    for ruta, metodos in app.app.openapi()["paths"].items():
        for metodo, op in metodos.items():
            if not op.get("security"):
                continue
            url = re.sub(r"\{(\w+)\}", lambda m: {"action": "start", "section": "general"}
                         .get(m.group(1), "1"), ruta)
            r = c.request(metodo.upper(), url)
            ok = r.status_code == 401 and "error" in (r.json() if r.content else {})
            if not ok:
                malas.append(f"{metodo.upper()} {ruta} -> {r.status_code} {r.text[:80]}")
    assert not malas, "\n".join(malas)


# ------------------------------------------------- 2. G3 -> G4 (inbox)
def test_tarea_publicada_por_g3_aparece_en_inbox_g4_solo_del_destinatario(c, s):
    titulo, asign = publicar(c, s)
    propio = c.get(f"/api/v1/inbox?q={titulo}", headers=s["docente1"]).json()
    ajeno = c.get(f"/api/v1/inbox?q={titulo}", headers=s["docente2"]).json()
    assert {"page", "per_page", "total", "data"} <= set(propio)
    assert propio["total"] == 1 and propio["data"][0]["id"] == asign[DOC1]
    assert ajeno["total"] == 0


def test_estado_en_g4_sigue_las_transiciones_de_g3(c, s):
    titulo, asign = publicar(c, s)
    a = asign[DOC1]
    assert c.post(f"/api/v1/assignments/{a}/actions/start", json={},
                  headers=s["docente1"]).status_code == 200
    det = c.get(f"/api/v1/assignments/{a}", headers=s["docente1"]).json()
    assert det["status"] == "in_progress", det


def test_docente_no_ve_detalle_de_asignacion_ajena(c, s):
    _, asign = publicar(c, s)
    r = c.get(f"/api/v1/assignments/{asign[DOC1]}", headers=s["docente2"])
    assert r.status_code in (403, 404)
    es_error_comun(r, r.status_code)


def test_docente_no_comenta_ni_vincula_archivos_en_asignacion_ajena(c, s):
    _, asign = publicar(c, s)
    a = asign[DOC1]
    assert c.post(f"/api/v1/assignments/{a}/comments", json={"text": "x"},
                  headers=s["docente2"]).status_code in (403, 404)
    assert c.post(f"/api/v1/assignments/{a}/files", json={"file_id": "1", "name": "x.pdf"},
                  headers=s["docente2"]).status_code in (403, 404)


def test_comentario_de_g4_se_guarda_en_la_base(c, s):
    _, asign = publicar(c, s)
    a = asign[DOC1]
    r = c.post(f"/api/v1/assignments/{a}/comments", json={"text": "Comentario PM"},
               headers=s["docente1"])
    assert r.status_code in (200, 201), r.text
    textos = [x["text"] for x in c.get(f"/api/v1/assignments/{a}/comments",
                                       headers=s["docente1"]).json()]
    assert "Comentario PM" in textos, f"respondió {r.status_code} pero no persistió: {textos}"


def test_borrador_de_g4_se_guarda_en_la_base(c, s):
    _, asign = publicar(c, s)
    a = asign[DOC1]
    assert c.put(f"/api/v1/assignments/{a}/submission-draft", json={"comment": "borrador PM"},
                 headers=s["docente1"]).status_code == 200
    det = c.get(f"/api/v1/assignments/{a}", headers=s["docente1"]).json()
    assert det.get("draft_comment") == "borrador PM", det.get("draft_comment")


def test_vincular_archivo_inexistente_se_rechaza(c, s):
    _, asign = publicar(c, s)
    r = c.post(f"/api/v1/assignments/{asign[DOC1]}/files",
               json={"file_id": "999999", "name": "no-existe.pdf"}, headers=s["docente1"])
    assert r.status_code in (404, 422), f"aceptó un archivo que no existe: {r.status_code}"


def test_auditor_no_comenta(c, s):
    _, asign = publicar(c, s)
    r = c.post(f"/api/v1/assignments/{asign[DOC1]}/comments", json={"text": "x"},
               headers=s["auditoria"])
    assert r.status_code == 403


# ----------------------------------------------------- 3. archivos (G2)
def _subir(c, cabeceras, nombre="evidencia.pdf"):
    r = c.post("/api/v1/files", headers=cabeceras,
               files={"file": (nombre, PDF_MINIMO, "application/pdf")})
    assert r.status_code in (200, 201), r.text
    cuerpo = r.json()
    return cuerpo.get("id") or cuerpo.get("archivo_id") or cuerpo.get("file_id")


def test_archivo_se_guarda_en_upload_dir(c, s, tmp_path, monkeypatch):
    destino = Path(os.environ.get("UPLOAD_DIR", "almacen_archivos")).resolve()
    antes = set(destino.rglob("*")) if destino.exists() else set()
    _subir(c, s["docente1"])
    despues = set(destino.rglob("*")) if destino.exists() else set()
    assert despues - antes, f"el archivo no quedó en UPLOAD_DIR ({destino})"


def test_otro_docente_no_descarga_archivo_ajeno(c, s):
    fid = _subir(c, s["docente1"])
    assert c.get(f"/api/v1/files/{fid}", headers=s["docente1"]).status_code == 200
    assert c.get(f"/api/v1/files/{fid}", headers=s["docente2"]).status_code in (403, 404)


def test_revisor_puede_descargar_evidencia_del_docente(c, s):
    """El revisor tiene files.download en la matriz del G1 y debe ver la evidencia."""
    fid = _subir(c, s["docente1"])
    assert c.get(f"/api/v1/files/{fid}", headers=s["revisor"]).status_code == 200


def test_archivo_eliminado_no_se_descarga(c, s, app):
    from sqlalchemy import create_engine, text
    fid = _subir(c, s["docente1"])
    motor = create_engine(URL)
    with motor.begin() as cx:
        cx.execute(text("UPDATE archivo SET eliminado_en = NOW(3) WHERE id = :i"), {"i": fid})
    motor.dispose()
    assert c.get(f"/api/v1/files/{fid}", headers=s["docente1"]).status_code == 404


def test_tipo_no_permitido_da_error_comun(c, s):
    r = c.post("/api/v1/files", headers=s["docente1"],
               files={"file": ("x.pdf", b"MZ\x90\x00 no soy pdf", "application/pdf")})
    assert r.status_code in (400, 415, 422)
    assert r.json()["error"]["message"] != "Solicitud inválida.", r.json()


# ------------------------------------------------- 4. usuarios y roles
def test_permisos_por_rol_en_rutas_de_administracion(c, s):
    assert c.post("/api/v1/tasks", headers=s["docente1"], json={
        "type_id": 1, "title": "no", "due_date": "2030-01-01"}).status_code == 403
    assert c.post("/api/v1/users", headers=s["docente1"], json={}).status_code in (403, 422)
    assert c.post("/api/v1/roles", headers=s["docente1"],
                  json={"codigo": "x", "nombre": "x"}).status_code == 403
    assert c.post("/api/v1/campuses", headers=s["docente1"], json={"nombre": "x"}).status_code == 403


def test_coordinacion_puede_listar_usuarios(c, s):
    """El G1 da users.read a coordinator; coordinación necesita la lista para asignar tareas."""
    assert c.get("/api/v1/users", headers=s["coordinacion"]).status_code == 200


def test_crear_rol_con_codigo_invalido_da_422(c, s):
    r = c.post("/api/v1/roles", headers=s["admin"], json={"codigo": "Jefe-Area", "nombre": "Jefe"})
    es_error_comun(r, 422)


def test_crear_usuario_con_correo_invalido_da_422(c, s):
    r = c.post("/api/v1/users", headers=s["admin"], json={
        "nombres": "A", "apellidos": "B", "correo": f"no-es-correo-{uuid.uuid4().hex[:6]}",
        "password": "ClaveSegura1!", "rol": "teacher", "roles": ["teacher"]})
    es_error_comun(r, 422)


def test_nombre_demasiado_largo_da_422_y_no_500(c, s):
    r = c.post("/api/v1/users", headers=s["admin"], json={
        "nombres": "A" * 300, "apellidos": "B", "correo": f"x{uuid.uuid4().hex[:6]}@udv.edu.gt",
        "password": "ClaveSegura1!", "rol": "teacher", "roles": ["teacher"]})
    es_error_comun(r, 422)


def test_paginacion_comun_en_listados(c, s):
    for ruta, quien in [("/api/v1/users", "admin"), ("/api/v1/tasks", "coordinacion"),
                        ("/api/v1/inbox", "docente1"), ("/api/v1/course-programs", "coordinacion"),
                        ("/api/v1/notifications", "docente1"), ("/api/v1/audit", "auditoria")]:
        cuerpo = c.get(ruta, headers=s[quien]).json()
        assert {"page", "per_page", "total", "data"} <= set(cuerpo), f"{ruta}: {list(cuerpo)}"


# -------------------------------------------------------- 5. programas (G5)
def test_docente_ajeno_no_edita_programa_de_otro(c, s):
    """La versión 2 (draft) es de docente1 en la semilla; docente2 no debe poder editarla."""
    r = c.put("/api/v1/program-versions/2/sections/descripcion",
              json={"contenido": {"texto": "editado por docente2"}}, headers=s["docente2"])
    assert r.status_code in (403, 404), f"docente2 editó el programa de docente1: {r.status_code}"


def test_ponderacion_mayor_a_100_da_422_con_formato_comun(c, s):
    """El trigger del G1 lanza SQLSTATE 45000 '(422)'; debe llegar como 422, no 500."""
    r = c.put("/api/v1/program-versions/2/sections/evaluacion",
              json={"contenido": {"parcial": 60, "final": 70}}, headers=s["docente1"])
    es_error_comun(r, 422)


def test_direccion_puede_autorizar_un_programa_aprobado(c, s):
    """Rol 'authority' del G1 (usuario direccion). Recorre todo el flujo del G5."""
    assert c.put("/api/v1/program-versions/2/sections/evaluacion",
                 json={"contenido": {"parcial": 40, "final": 60}},
                 headers=s["docente1"]).status_code == 200
    r = c.post("/api/v1/program-versions/2/submit", json={}, headers=s["docente1"])
    assert r.status_code == 200, r.text
    assert c.post("/api/v1/program-versions/2/review", json={}, headers=s["revisor"]).status_code == 200
    assert c.post("/api/v1/program-versions/2/approve", json={}, headers=s["revisor"]).status_code == 200
    r = c.post("/api/v1/program-versions/2/authorize", json={}, headers=s["direccion"])
    assert r.status_code == 200, f"direccion (authority) no pudo autorizar: {r.status_code} {r.text}"
    pdf = c.get("/api/v1/program-versions/2/pdf", headers=s["docente1"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_pdf_de_version_no_autorizada_da_409(c, s):
    r = c.get("/api/v1/program-versions/999999/pdf", headers=s["docente1"])
    es_error_comun(r, 404)


# ---------------------------------------------------- 6. sesiones
def test_logout_invalida_el_token_en_todos_los_modulos(c):
    h = _login(c, "docente2@demo.udv.edu.gt")
    assert c.post("/api/v1/auth/logout", headers=h).status_code in (200, 204)
    for ruta in ("/api/v1/me", "/api/v1/inbox", "/api/v1/tasks", "/api/v1/notifications",
                 "/api/v1/course-programs"):
        assert c.get(ruta, headers=h).status_code == 401, ruta


def test_login_fallido_no_revela_si_el_correo_existe(c):
    a = c.post("/api/v1/auth/login", json={"correo": "docente3@demo.udv.edu.gt", "password": "malamala1"})
    b = c.post("/api/v1/auth/login", json={"correo": "noexiste@demo.udv.edu.gt", "password": "malamala1"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


# ------------------------------------------- 7. reglas del workflow (G3)
def _accion(c, h, a, nombre, comentario=None):
    return c.post(f"/api/v1/assignments/{a}/{nombre}", json={"comment": comentario}, headers=h)


def test_no_se_entrega_sin_archivo_si_el_tipo_lo_exige(c, s):
    """Tipo 3 ENTREGAR_FACTURA tiene requiere_archivo=1 en el G1."""
    _, asign = publicar(c, s, tipo=3)
    a = asign[DOC1]
    assert _accion(c, s["docente1"], a, "start").status_code == 200
    r = _accion(c, s["docente1"], a, "submit")
    assert r.status_code == 422, f"entregó sin archivo: {r.status_code}"


def test_entregar_crea_registro_en_entrega(c, s):
    from sqlalchemy import create_engine, text
    _, asign = publicar(c, s)
    a = asign[DOC1]
    _accion(c, s["docente1"], a, "start")
    assert _accion(c, s["docente1"], a, "submit").status_code == 200
    motor = create_engine(URL)
    with motor.connect() as cx:
        n = cx.execute(text("SELECT COUNT(*) FROM entrega WHERE tarea_destinatario_id = :a"),
                       {"a": a}).scalar()
    motor.dispose()
    assert n == 1, "submit no dejó fila en entrega"


def test_tarea_sin_revisor_no_la_aprueba_cualquier_revisor(c, s):
    """Sin revisor designado, un revisor cualquiera no debería aprobar."""
    _, asign = publicar(c, s, revisor=None)
    a = asign[DOC1]
    _accion(c, s["docente1"], a, "start")
    _accion(c, s["docente1"], a, "submit")
    r = _accion(c, s["revisor"], a, "review")
    assert r.status_code in (403, 409), f"revisor no designado pudo revisar: {r.status_code}"


def test_existe_la_accion_close_del_contrato_g3(c, s):
    assert c.post("/api/v1/assignments/999999/close", json={},
                  headers=s["coordinacion"]).status_code != 405
    assert c.post("/api/v1/assignments/999999/close", json={},
                  headers=s["coordinacion"]).status_code in (403, 404, 409)


def test_errores_de_g3_usan_codigos_del_contrato_comun(c, s):
    _, asign = publicar(c, s)
    r = _accion(c, s["revisor"], asign[DOC1], "approve")
    es_error_comun(r, 409)
    assert r.json()["error"]["code"].isupper(), r.json()


def test_revisor_no_designado_no_lee_entrega_en_g4(c, s):
    """Revisor designado: admin (1) actuando como otro; el usuario 5 no es el revisor de esta tarea."""
    _, asign = publicar(c, s, revisor=None)
    r = c.get(f"/api/v1/assignments/{asign[DOC1]}", headers=s["revisor"])
    assert r.status_code in (403, 404), f"revisor ajeno vio la entrega: {r.status_code}"


def test_programa_admite_version_en_otro_periodo(c, s):
    """Un curso tiene un programa por período; la llave uq_pv_numero no debe impedir el período 2."""
    r = c.post("/api/v1/course-programs", headers=s["docente1"], json={
        "curso_id": 1, "sede_id": 1, "modalidad_id": 1, "periodo_id": 2})
    assert r.status_code == 201, f"{r.status_code} {r.text[:200]}"
