"""Pruebas de G4 que ESCRIBEN en MySQL, con la app completa de la raíz (G2 + G3 + G4).

Cubren los hallazgos de QA del 12 y 13 de noviembre: comentarios y borrador
en la base, archivo inexistente, fila de entrega por intento y reenvío con
archivo nuevo. Para el flujo usan los servicios reales: G2 sube el archivo,
G3 hace start, submit, review, return y resubmit.

Escriben tareas, archivos y entregas: usar SOLO una base desechable (la del
docker-compose de la raíz), nunca la de Railway. Usan la misma variable que
las pruebas de integración del PM:

    set UDV_TEST_MYSQL_URL=mysql+pymysql://udv_app:<clave>@127.0.0.1:3307/db_udv
    py -m pytest tests/test_mysql_escritura.py -v
"""
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

URL = os.environ.get("UDV_TEST_MYSQL_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Define UDV_TEST_MYSQL_URL (base desechable)")

RAIZ = Path(__file__).resolve().parents[3]   # carpeta raíz del repo
DOC1, DOC2, REVISOR = 3, 4, 5                # ids de la semilla de G1
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


@pytest.fixture(scope="module")
def c():
    os.environ.setdefault("SECRET_KEY", "clave-solo-para-pruebas-de-g4-con-32-caracteres")
    sys.path.insert(0, str(RAIZ))
    import importlib
    import g4_inbox.routes as routes
    raiz = importlib.import_module("main")
    viejo = routes.USAR_MYSQL
    routes.USAR_MYSQL = True     # conftest.py lo apaga para las demás pruebas
    from fastapi.testclient import TestClient
    with TestClient(raiz.app, raise_server_exceptions=False) as cliente:
        yield cliente
    routes.USAR_MYSQL = viejo


@pytest.fixture(scope="module")
def s(c):
    def entrar(correo):
        r = c.post("/api/v1/auth/login", json={"correo": correo, "password": "Demo2026!"})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    return {k: entrar(f"{k}@demo.udv.edu.gt") for k in ("coordinacion", "docente1", "docente2", "revisor")}


def _consulta(sql, **parametros):
    from sqlalchemy import create_engine, text
    motor = create_engine(URL)
    with motor.connect() as cx:
        filas = cx.execute(text(sql), parametros).all()
    motor.dispose()
    return filas


def publicar(c, s, tipo=3, revisor=REVISOR):
    """Crea y publica una tarea con G3 para el docente 1. Devuelve el id de la asignación."""
    cuerpo = {"type_id": tipo, "title": f"G4TEST-{uuid.uuid4().hex[:6]}",
              "due_date": (date.today() + timedelta(days=10)).isoformat()}
    if revisor:
        cuerpo["reviewer_id"] = revisor
    r = c.post("/api/v1/tasks", headers=s["coordinacion"], json=cuerpo)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert c.post(f"/api/v1/tasks/{tid}/recipients", headers=s["coordinacion"],
                  json={"mode": "users", "user_ids": [DOC1]}).status_code == 200
    assert c.post(f"/api/v1/tasks/{tid}/publish", headers=s["coordinacion"]).status_code == 200
    asignaciones = c.get(f"/api/v1/tasks/{tid}/assignments", headers=s["coordinacion"]).json()
    asignaciones = asignaciones.get("data") or asignaciones.get("items") or []
    return asignaciones[0]["id"]


def subir(c, cabeceras, nombre):
    r = c.post("/api/v1/files", headers=cabeceras, files={"file": (nombre, PDF, "application/pdf")})
    assert r.status_code in (200, 201), r.text
    return r.json()["file_id"]


def accion(c, cabeceras, a, nombre, comentario=None):
    r = c.post(f"/api/v1/assignments/{a}/{nombre}", headers=cabeceras, json={"comment": comentario})
    assert r.status_code == 200, f"{nombre}: {r.status_code} {r.text}"


# ------------------------------------------------------------ comentarios y borrador (#3)
def test_comentario_se_guarda_en_la_tabla_comentario(c, s):
    a = publicar(c, s)
    r = c.post(f"/api/v1/assignments/{a}/comments", headers=s["docente1"], json={"text": "hola G4"})
    assert r.status_code == 200, r.text
    assert _consulta("SELECT contenido FROM comentario WHERE tarea_destinatario_id = :a", a=a) == [("hola G4",)]
    textos = [x["text"] for x in c.get(f"/api/v1/assignments/{a}/comments", headers=s["docente1"]).json()]
    assert textos == ["hola G4"]


def test_borrador_se_guarda_y_se_reemplaza(c, s):
    a = publicar(c, s)
    for texto in ("primera versión", "segunda versión"):
        r = c.put(f"/api/v1/assignments/{a}/submission-draft", headers=s["docente1"], json={"comment": texto})
        assert r.status_code == 200, r.text
    assert c.get(f"/api/v1/assignments/{a}", headers=s["docente1"]).json()["draft_comment"] == "segunda versión"
    assert len(_consulta("SELECT id FROM entrega_borrador WHERE tarea_destinatario_id = :a", a=a)) == 1


def test_borrador_de_una_entrega_ya_enviada_da_409(c, s):
    a = publicar(c, s, tipo=1)
    accion(c, s["docente1"], a, "start")
    accion(c, s["docente1"], a, "submit")
    r = c.put(f"/api/v1/assignments/{a}/submission-draft", headers=s["docente1"], json={"comment": "tarde"})
    assert r.status_code == 409, r.text


# ------------------------------------------------------------ archivos (#4)
def test_archivo_que_no_existe_da_404(c, s):
    a = publicar(c, s)
    r = c.post(f"/api/v1/assignments/{a}/files", headers=s["docente1"], json={"file_id": "999999", "name": "x.pdf"})
    assert r.status_code == 404, r.text
    assert set(r.json()) == {"error"}   # formato de error común de G2


def test_archivo_eliminado_da_404(c, s):
    a = publicar(c, s)
    fid = subir(c, s["docente1"], "borrado.pdf")
    from sqlalchemy import create_engine, text
    motor = create_engine(URL)
    with motor.begin() as cx:
        cx.execute(text("UPDATE archivo SET eliminado_en = NOW(3) WHERE id = :f"), {"f": fid})
    motor.dispose()
    r = c.post(f"/api/v1/assignments/{a}/files", headers=s["docente1"], json={"file_id": str(fid), "name": "borrado.pdf"})
    assert r.status_code == 404, r.text


def test_no_se_vincula_un_archivo_de_otro_usuario(c, s):
    a = publicar(c, s)
    ajeno = subir(c, s["docente2"], "ajeno.pdf")
    r = c.post(f"/api/v1/assignments/{a}/files", headers=s["docente1"], json={"file_id": str(ajeno), "name": "ajeno.pdf"})
    assert r.status_code == 404, r.text
    assert _consulta("SELECT entrega_id FROM archivo WHERE id = :f", f=ajeno) == [(None,)]


def test_vincular_crea_la_entrega_y_no_la_duplica(c, s):
    a = publicar(c, s)
    accion(c, s["docente1"], a, "start")
    f1, f2 = subir(c, s["docente1"], "uno.pdf"), subir(c, s["docente1"], "dos.pdf")
    for fid in (f1, f2, f1):   # el tercero repite: no debe crear otra entrega
        r = c.post(f"/api/v1/assignments/{a}/files", headers=s["docente1"], json={"file_id": str(fid), "name": "x"})
        assert r.status_code == 200, r.text
        assert r.json()["numero_intento"] == 1
    entregas = _consulta("SELECT id, numero_intento FROM entrega WHERE tarea_destinatario_id = :a", a=a)
    assert len(entregas) == 1
    vinculados = _consulta("SELECT id FROM archivo WHERE entrega_id = :e ORDER BY id", e=entregas[0][0])
    assert [x[0] for x in vinculados] == sorted([f1, f2])


def test_no_se_vincula_archivo_despues_de_entregar(c, s):
    a = publicar(c, s, tipo=1)
    accion(c, s["docente1"], a, "start")
    accion(c, s["docente1"], a, "submit")
    fid = subir(c, s["docente1"], "tarde.pdf")
    r = c.post(f"/api/v1/assignments/{a}/files", headers=s["docente1"], json={"file_id": str(fid), "name": "tarde.pdf"})
    assert r.status_code == 409, r.text


def test_reenvio_con_archivo_nuevo_crea_un_segundo_intento(c, s):
    """La prueba que pidió el PM el 13-nov: resubmit con archivo nuevo."""
    a = publicar(c, s)
    accion(c, s["docente1"], a, "start")
    primero = subir(c, s["docente1"], "factura_v1.pdf")
    assert c.post(f"/api/v1/assignments/{a}/files", headers=s["docente1"],
                  json={"file_id": str(primero), "name": "factura_v1.pdf"}).json()["numero_intento"] == 1
    accion(c, s["docente1"], a, "submit")
    accion(c, s["revisor"], a, "review")
    accion(c, s["revisor"], a, "return", "El monto no coincide")

    assert c.put(f"/api/v1/assignments/{a}/submission-draft", headers=s["docente1"],
                 json={"comment": "Corregí el monto"}).status_code == 200
    segundo = subir(c, s["docente1"], "factura_v2.pdf")
    r = c.post(f"/api/v1/assignments/{a}/files", headers=s["docente1"],
               json={"file_id": str(segundo), "name": "factura_v2.pdf"})
    assert r.status_code == 200, r.text
    assert r.json()["numero_intento"] == 2
    accion(c, s["docente1"], a, "resubmit")

    entregas = dict(_consulta("SELECT numero_intento, id FROM entrega WHERE tarea_destinatario_id = :a", a=a))
    assert sorted(entregas) == [1, 2]
    # el reenvío conserva la evidencia anterior en su intento: nunca se borra ni se mueve
    assert _consulta("SELECT entrega_id FROM archivo WHERE id = :f", f=primero) == [(entregas[1],)]
    assert _consulta("SELECT entrega_id FROM archivo WHERE id = :f", f=segundo) == [(entregas[2],)]
    archivos = c.get(f"/api/v1/assignments/{a}", headers=s["revisor"]).json()["files"]
    assert [(f["name"], f["attempt"], f["mime"]) for f in archivos] == [
        ("factura_v1.pdf", 1, "application/pdf"), ("factura_v2.pdf", 2, "application/pdf")]
    assert all(f["size"] > 0 for f in archivos)
    # el revisor puede descargar la evidencia (lo valida G2)
    r = c.get(f"/api/v1/files/{archivos[1]['file_id']}", headers=s["revisor"])
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    # la entrega que creó G4 lleva el texto del borrador (G1 no deja agregarlo después)
    assert _consulta("SELECT contenido_texto FROM entrega WHERE id = :e", e=entregas[2]) == [("Corregí el monto",)]


def test_reenvio_sin_archivo_nuevo_lo_rechaza_g3(c, s):
    """Si el tipo exige archivo, el intento nuevo debe tener uno. Esta prueba falla si
    G4 y G3 guardan las fechas en zonas horarias distintas: G3 vería abierto el intento 1."""
    a = publicar(c, s)
    accion(c, s["docente1"], a, "start")
    fid = subir(c, s["docente1"], "unico.pdf")
    assert c.post(f"/api/v1/assignments/{a}/files", headers=s["docente1"],
                  json={"file_id": str(fid), "name": "unico.pdf"}).status_code == 200
    accion(c, s["docente1"], a, "submit")
    accion(c, s["revisor"], a, "review")
    accion(c, s["revisor"], a, "return", "Sube la versión firmada")
    r = c.post(f"/api/v1/assignments/{a}/resubmit", headers=s["docente1"], json={"comment": None})
    assert r.status_code == 422, r.text


def test_primer_envio_sin_archivo_y_reenvio_con_dos_archivos_usa_un_solo_intento(c, s):
    """El primer envío es el intento 1 (lo crea G3); los dos archivos del reenvío van juntos al 2."""
    a = publicar(c, s, tipo=1)   # tipo que no exige archivo
    accion(c, s["docente1"], a, "start")
    accion(c, s["docente1"], a, "submit")
    accion(c, s["revisor"], a, "review")
    accion(c, s["revisor"], a, "return", "Falta el respaldo")
    for nombre in ("respaldo_a.pdf", "respaldo_b.pdf"):
        fid = subir(c, s["docente1"], nombre)
        r = c.post(f"/api/v1/assignments/{a}/files", headers=s["docente1"], json={"file_id": str(fid), "name": nombre})
        assert r.status_code == 200, r.text
        assert r.json()["numero_intento"] == 2
    # 1 = el primer envío (G3 crea la fila si no existe; antes del 14-nov no la creaba)
    numeros = [x[0] for x in _consulta("SELECT numero_intento FROM entrega WHERE tarea_destinatario_id = :a", a=a)]
    assert sorted(numeros) in ([1, 2], [2]) and numeros.count(2) == 1


# ------------------------------------------------------------ devolución visible
def test_el_docente_ve_la_observacion_y_la_fecha_de_la_devolucion(c, s):
    """Criterio de aceptación: una devolución exige observación visible para el docente."""
    a = publicar(c, s, tipo=1)
    accion(c, s["docente1"], a, "start")
    accion(c, s["docente1"], a, "submit")
    accion(c, s["revisor"], a, "review")
    accion(c, s["revisor"], a, "return", "Falta la bibliografía de la unidad 3")
    d = c.get(f"/api/v1/assignments/{a}", headers=s["docente1"]).json()
    assert d["last_return"]["comment"] == "Falta la bibliografía de la unidad 3"
    assert d["last_return"]["at"]                      # con fecha
    # el historial sale en el orden en que pasó, aunque las fechas vengan en zonas distintas
    assert [h["new_status"] for h in d["history"]] == [
        "assigned", "in_progress", "submitted", "under_review", "returned"]


def test_el_comentario_al_aprobar_se_guarda_y_lo_ve_el_docente(c, s):
    a = publicar(c, s, tipo=1)
    accion(c, s["docente1"], a, "start")
    accion(c, s["docente1"], a, "submit")
    accion(c, s["revisor"], a, "review")
    accion(c, s["revisor"], a, "approve", "Muy completo, gracias")
    d = c.get(f"/api/v1/assignments/{a}", headers=s["docente1"]).json()
    assert d["status"] == "approved"
    assert d["last_approval"]["comment"] == "Muy completo, gracias" and d["last_approval"]["at"]


# ------------------------------------------------------------ revisor designado
def test_solo_el_revisor_designado_ve_la_asignacion(c, s):
    con_revisor = publicar(c, s, revisor=REVISOR)
    sin_revisor = publicar(c, s, revisor=None)
    assert c.get(f"/api/v1/assignments/{con_revisor}", headers=s["revisor"]).status_code == 200
    assert c.get(f"/api/v1/assignments/{sin_revisor}", headers=s["revisor"]).status_code == 403
