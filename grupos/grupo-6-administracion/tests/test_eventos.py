"""G6-17: los cambios de G3, G4 y G5 se convierten en notificaciones.

En MySQL, los triggers del G1 escriben una fila en `evento` cuando una tarea
se publica o se cancela, cuando una entrega cambia de estado y cuando se
autoriza un programa. Aquí se insertan esas mismas filas a mano (SQLite no
tiene los triggers) y se revisa que el G6 avise a quien corresponde. La
prueba con los triggers reales está en tests/integracion/test_mysql_g1.py.
"""

import json
from datetime import datetime

import pytest
from conftest import ADMINISTRACION, DOCENTE
from sqlalchemy import insert, select

from g6_admin import tablas
from g6_admin.notificaciones import RepositorioNotificaciones, ServicioNotificaciones

DOCENTE_ID, REVISOR_ID, COORDINADOR_ID, OTRO_COORDINADOR_ID = DOCENTE.id, 5, 7, 8
CREADOR_ID = ADMINISTRACION.id


@pytest.fixture(autouse=True)
def datos_de_otros_grupos(fabrica):
    """Una tarea con una asignación al docente y un programa, como los dejan G3 y G5."""
    with fabrica.begin() as s:
        s.execute(insert(tablas.usuario), [{"id": u, "activo": True} for u in (
            DOCENTE_ID, REVISOR_ID, COORDINADOR_ID, OTRO_COORDINADOR_ID, CREADOR_ID)])
        s.execute(insert(tablas.rol), [{"id": 2, "codigo": "coordinator", "activo": True}])
        s.execute(insert(tablas.usuario_rol), [{"usuario_id": COORDINADOR_ID, "rol_id": 2},
                                              {"usuario_id": OTRO_COORDINADOR_ID, "rol_id": 2}])
        s.execute(insert(tablas.tarea).values(
            id=10, titulo="Actualizar sílabo", creado_por=CREADOR_ID, revisor_id=REVISOR_ID,
            fecha_limite=datetime(2026, 11, 15, 23, 59)))
        s.execute(insert(tablas.tarea_destinatario).values(
            id=20, tarea_id=10, usuario_id=DOCENTE_ID, estado_codigo="submitted"))
        s.execute(insert(tablas.programa_version).values(
            id=30, nombre="Programación Web v2", creado_por=DOCENTE_ID,
            docente_responsable_id=DOCENTE_ID))


def evento_de_trigger(fabrica, nombre, clave, **columnas):
    """Inserta la fila que dejaría el trigger del G1."""
    payload = columnas.pop("payload", None)
    with fabrica.begin() as s:
        return s.execute(insert(tablas.evento).values(
            nombre=nombre, clave_unica=clave, creado_en=datetime(2026, 10, 23),
            payload=json.dumps(payload) if payload else None, **columnas)
        ).inserted_primary_key[0]


@pytest.fixture
def servicio(sesion) -> ServicioNotificaciones:
    return ServicioNotificaciones(RepositorioNotificaciones(sesion))


def avisos(sesion):
    n = tablas.notificacion
    return [(f.usuario_id, f.tipo, f.mensaje) for f in sesion.execute(select(n).order_by(n.c.id))]


@pytest.mark.parametrize("nombre, columnas, destinatarios, texto", [
    ("task.published", {"tarea_id": 10}, [DOCENTE_ID], "2026-11-15 23:59"),
    ("task.cancelled", {"tarea_id": 10}, [DOCENTE_ID], "fue cancelada"),
    ("assignment.due_soon", {"tarea_id": 10, "tarea_destinatario_id": 20},
     [DOCENTE_ID], "vence el 2026-11-15"),
    ("assignment.submitted", {"tarea_id": 10, "tarea_destinatario_id": 20},
     [REVISOR_ID], "lista para revisión"),
    ("assignment.returned", {"tarea_id": 10, "tarea_destinatario_id": 20,
                             "payload": {"comentario": "Falta la bibliografía."}},
     [DOCENTE_ID], "Observación: Falta la bibliografía."),
    ("assignment.approved", {"tarea_id": 10, "tarea_destinatario_id": 20},
     [DOCENTE_ID, CREADOR_ID], "fue aprobada"),
    ("program.authorized", {"programa_version_id": 30},
     [DOCENTE_ID, COORDINADOR_ID, OTRO_COORDINADOR_ID], "Programación Web v2"),
])
def test_cada_evento_del_g1_llega_a_quien_corresponde(fabrica, sesion, servicio, nombre,
                                                      columnas, destinatarios, texto):
    evento_de_trigger(fabrica, nombre, f"{nombre}:1", **columnas)

    resumen = servicio.procesar_pendientes()

    assert resumen == {"processed": 1, "notifications": len(destinatarios), "failed": 0}
    guardadas = avisos(sesion)
    assert [u for u, _, _ in guardadas] == destinatarios
    assert all(tipo == nombre and texto in mensaje for _, tipo, mensaje in guardadas)


def test_el_evento_queda_procesado_y_no_se_repite(fabrica, sesion, servicio):
    evento_id = evento_de_trigger(fabrica, "task.published", "task.published:10", tarea_id=10)

    servicio.procesar_pendientes()
    assert servicio.procesar_pendientes() == {"processed": 0, "notifications": 0, "failed": 0}

    assert len(avisos(sesion)) == 1
    procesado = sesion.execute(select(tablas.evento.c.procesado_en)
                               .where(tablas.evento.c.id == evento_id)).scalar_one()
    assert procesado is not None


def test_un_evento_que_falla_no_frena_los_demas(fabrica, sesion, servicio, monkeypatch):
    evento_de_trigger(fabrica, "task.published", "a", tarea_id=10)
    malo = evento_de_trigger(fabrica, "task.cancelled", "b", tarea_id=10)
    evento_de_trigger(fabrica, "assignment.submitted", "c", tarea_id=10, tarea_destinatario_id=20)

    original = servicio._armar

    def armar(fila):
        if fila.id == malo:
            raise ConnectionError("se cayó la base")
        return original(fila)

    monkeypatch.setattr(servicio, "_armar", armar)
    assert servicio.procesar_pendientes() == {"processed": 2, "notifications": 2, "failed": 1}
    # El que falló sigue pendiente y no dejó nada a medias (G6-18).
    assert [t for _, t, _ in avisos(sesion)] == ["task.published", "assignment.submitted"]
    pendientes = sesion.execute(select(tablas.evento.c.id)
                                .where(tablas.evento.c.procesado_en.is_(None))).scalars()
    assert list(pendientes) == [malo]


def test_sin_destinatarios_se_marca_procesado_sin_avisos(fabrica, sesion, servicio):
    # Una tarea sin revisor: la entrega no tiene a quién avisar.
    with fabrica.begin() as s:
        s.execute(insert(tablas.tarea).values(id=11, titulo="Sin revisor", creado_por=1))
        s.execute(insert(tablas.tarea_destinatario).values(id=21, tarea_id=11, usuario_id=2))
    evento_de_trigger(fabrica, "assignment.submitted", "x", tarea_id=11, tarea_destinatario_id=21)

    assert servicio.procesar_pendientes() == {"processed": 1, "notifications": 0, "failed": 0}


def test_al_listar_se_procesan_los_eventos_nuevos(fabrica, docente):
    evento_de_trigger(fabrica, "task.published", "task.published:10", tarea_id=10)

    datos = docente.get("/api/v1/notifications").json()

    assert [n["event"] for n in datos["data"]] == ["task.published"]
    assert datos["data"][0]["title"] == "Nueva tarea asignada"


def test_administracion_puede_procesar_a_demanda(fabrica, admin, docente):
    evento_de_trigger(fabrica, "task.cancelled", "task.cancelled:10", tarea_id=10)

    assert docente.post("/api/v1/notifications/process").status_code == 403
    respuesta = admin.post("/api/v1/notifications/process")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"processed": 1, "notifications": 1, "failed": 0}
