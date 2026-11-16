"""Pruebas del panel de indicadores: escenarios G6-26 a G6-29.

Los datos se arman a mano en las tablas del G1 para saber de antemano cuánto
debe dar cada número. "Ahora" es fijo para que las fechas no dependan del día
en que corren las pruebas.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import insert

from conftest import _cliente, _usuario
from g6_admin import tablas
from g6_admin.auditoria import ESTADOS_TAREA
from g6_admin.panel import ORDEN_ESTADOS, RepositorioPanel, ServicioPanel

AHORA = datetime(2026, 11, 2, 12, 0)
AYER = AHORA - timedelta(days=1)


def _filas(*filas: dict) -> list[dict]:
    # Una inserción de varias filas necesita las mismas columnas en todas.
    columnas = {c for f in filas for c in f}
    return [{c: f.get(c) for c in columnas} for f in filas]


@pytest.fixture
def datos(fabrica):
    """Tareas y asignaciones con un resultado conocido.

    | Asignación | Tarea (estado)           | Estado      | Vence        | Cuenta como |
    |------------|--------------------------|-------------|--------------|-------------|
    | 1          | 1 Planificación (assigned) | assigned  | ayer (tarea) | vencida     |
    | 2          | 1                        | submitted   | ayer         | cumplida    |
    | 3          | 1                        | returned    | en 2 días    | próxima     |
    | 4          | 2 CV (in_progress)       | in_progress | en 18 días   | pendiente   |
    | 5          | 2                        | approved    | en 18 días   | cumplida    |
    | 6          | 2                        | cancelled   | en 18 días   | no cuenta   |
    | 7          | 5 Cierre (closed)        | closed      | sin fecha    | cumplida    |
    | 8          | 2                        | assigned    | justo en 3 días | pendiente (fuera del plazo) |
    | 9          | 4 Borrada (eliminada)    | assigned    | ayer         | no cuenta   |
    | 10         | 6 Cancelada (cancelled)  | cancelled   | ayer         | no cuenta   |
    """
    with fabrica() as s:
        s.execute(insert(tablas.usuario), [
            {"id": 3, "correo": "docente1@demo.test", "nombres": "Diana", "apellidos": "Pérez"},
            {"id": 4, "correo": "docente2@demo.test", "nombres": "Daniel", "apellidos": "López"},
            {"id": 5, "correo": "revisor@demo.test", "nombres": "Rosa", "apellidos": "Revisora"},
            {"id": 8, "correo": "docente3@demo.test", "nombres": "María", "apellidos": "García"}])
        s.execute(insert(tablas.parametro).values(codigo="dias_aviso_vencimiento", valor="3"))
        s.execute(insert(tablas.tarea), _filas(
            {"id": 1, "titulo": "Planificación", "estado_codigo": "assigned", "fecha_limite": AYER},
            {"id": 2, "titulo": "CV", "estado_codigo": "in_progress",
             "fecha_limite": AHORA + timedelta(days=18)},
            {"id": 3, "titulo": "Borrador", "estado_codigo": "draft"},
            {"id": 4, "titulo": "Borrada", "estado_codigo": "assigned", "fecha_limite": AYER,
             "eliminado_en": AYER},
            {"id": 5, "titulo": "Cierre", "estado_codigo": "closed"},
            {"id": 6, "titulo": "Cancelada", "estado_codigo": "cancelled", "fecha_limite": AYER}))
        s.execute(insert(tablas.tarea_destinatario), _filas(
            {"id": 1, "tarea_id": 1, "usuario_id": 3, "estado_codigo": "assigned"},
            {"id": 2, "tarea_id": 1, "usuario_id": 4, "estado_codigo": "submitted"},
            {"id": 3, "tarea_id": 1, "usuario_id": 8, "estado_codigo": "returned",
             "fecha_limite": AHORA + timedelta(days=2)},
            {"id": 4, "tarea_id": 2, "usuario_id": 3, "estado_codigo": "in_progress"},
            {"id": 5, "tarea_id": 2, "usuario_id": 4, "estado_codigo": "approved"},
            {"id": 6, "tarea_id": 2, "usuario_id": 8, "estado_codigo": "cancelled"},
            {"id": 7, "tarea_id": 5, "usuario_id": 3, "estado_codigo": "closed"},
            {"id": 8, "tarea_id": 2, "usuario_id": 5, "estado_codigo": "assigned",
             "fecha_limite": AHORA + timedelta(days=3)},
            {"id": 9, "tarea_id": 4, "usuario_id": 3, "estado_codigo": "assigned"},
            {"id": 10, "tarea_id": 6, "usuario_id": 4, "estado_codigo": "cancelled"}))
        s.commit()
    return fabrica


def panel(fabrica, **opciones):
    with fabrica() as s:
        return ServicioPanel(RepositorioPanel(s)).indicadores(ahora=AHORA, **opciones)


# ── G6-26: tareas por estado ────────────────────────────────────────────────

def test_cuenta_tareas_por_estado_sin_las_eliminadas(datos):
    tareas = panel(datos)["tasks"]
    assert tareas["total"] == 5
    assert {e: n for e, n in tareas["by_state"].items() if n} == {
        "draft": 1, "assigned": 1, "in_progress": 1, "closed": 1, "cancelled": 1}


def test_cuenta_asignaciones_por_estado(datos):
    asignaciones = panel(datos)["assignments"]
    assert asignaciones["total"] == 9
    assert {e: n for e, n in asignaciones["by_state"].items() if n} == {
        "assigned": 2, "in_progress": 1, "submitted": 1, "returned": 1,
        "approved": 1, "closed": 1, "cancelled": 2}


def test_muestra_todos_los_estados_oficiales_en_orden(datos):
    assert set(ORDEN_ESTADOS) == ESTADOS_TAREA
    assert list(panel(datos)["tasks"]["by_state"]) == list(ORDEN_ESTADOS)


def test_sin_tareas_todo_en_cero(fabrica):
    resultado = panel(fabrica)
    assert resultado["tasks"]["total"] == resultado["assignments"]["total"] == 0
    assert set(resultado["tasks"]["by_state"].values()) == {0}
    assert resultado["overdue"] == resultado["due_soon"] == {"total": 0, "items": []}


# ── G6-27: vencidas ─────────────────────────────────────────────────────────

def test_vencidas_son_las_pendientes_con_fecha_pasada(datos):
    vencidas = panel(datos)["overdue"]
    assert vencidas["total"] == 1
    assert vencidas["items"] == [{
        "assignment_id": 1, "task_id": 1, "task_title": "Planificación",
        "user_id": 3, "user_email": "docente1@demo.test", "user_name": "Diana Pérez",
        "state": "assigned", "due_date": "2026-11-01T12:00:00Z"}]


def test_una_entrega_hecha_no_cuenta_como_vencida(datos):
    # La asignación 2 vence ayer pero ya se entregó (submitted).
    assert 2 not in {a["assignment_id"] for a in panel(datos)["overdue"]["items"]}


def test_una_tarea_cancelada_no_deja_vencidas(datos):
    # El G1 no cambia las asignaciones al cancelar la tarea: una puede quedar
    # en assigned. Como ya no hay nada que entregar, no cuenta como vencida.
    with datos() as s:
        s.execute(tablas.tarea_destinatario.update().where(
            tablas.tarea_destinatario.c.id == 10).values(estado_codigo="assigned"))
        s.commit()
    assert panel(datos)["overdue"]["total"] == 1


# ── G6-28: próximas a vencer ────────────────────────────────────────────────

def test_proximas_usan_los_dias_de_aviso_del_g1(datos):
    resultado = panel(datos)
    assert resultado["due_soon_days"] == 3
    assert [a["assignment_id"] for a in resultado["due_soon"]["items"]] == [3]
    # La 8 vence justo al final del plazo: queda fuera, igual que en v_panel_tarea.


def test_la_fecha_propia_de_la_asignacion_gana_a_la_de_la_tarea(datos):
    # La tarea 1 venció ayer, pero la asignación 3 tiene su propia fecha.
    proxima = panel(datos)["due_soon"]["items"][0]
    assert (proxima["task_id"], proxima["due_date"]) == (1, "2026-11-04T12:00:00Z")


def test_sin_ahora_usa_la_hora_de_la_base(datos):
    # La base dice qué hora es (NOW(3), igual que la vista del G1 y sus avisos
    # de vencimiento), no el reloj del servidor de la app. Esta base está en
    # Guatemala (UTC-6) y su reloj marca AHORA, aunque hoy sea otro día.
    class BaseEnGuatemala(RepositorioPanel):
        def reloj(self):
            return AHORA, -360

    with datos() as s:
        resultado = ServicioPanel(BaseEnGuatemala(s)).indicadores()
    assert resultado["generated_at"] == "2026-11-02T12:00:00-06:00"
    assert [a["assignment_id"] for a in resultado["due_soon"]["items"]] == [3]
    assert resultado["due_soon"]["items"][0]["due_date"] == "2026-11-04T12:00:00-06:00"
    assert resultado["overdue"]["total"] == 1


def test_el_reloj_de_la_base_de_pruebas_esta_en_utc(fabrica):
    with fabrica() as s:
        hora, desfase = RepositorioPanel(s).reloj()
    assert isinstance(hora, datetime) and desfase == 0


def test_mas_dias_de_aviso_amplian_la_lista(datos):
    with datos() as s:
        s.execute(tablas.parametro.update().values(valor="20"))
        s.commit()
    assert [a["assignment_id"] for a in panel(datos)["due_soon"]["items"]] == [3, 8, 4]


@pytest.mark.parametrize("valor", [None, "", "abc", "0", "-2"])
def test_sin_parametro_valido_usa_3_dias(fabrica, valor):
    if valor is not None:
        with fabrica() as s:
            s.execute(insert(tablas.parametro).values(codigo="dias_aviso_vencimiento",
                                                      valor=valor))
            s.commit()
    assert panel(fabrica)["due_soon_days"] == 3


def test_el_limite_corta_la_lista_pero_no_el_total(datos):
    with datos() as s:
        s.execute(tablas.parametro.update().values(valor="20"))
        s.commit()
    proximas = panel(datos, limite=2)["due_soon"]
    assert proximas["total"] == 3 and len(proximas["items"]) == 2


# ── G6-29: cumplimiento ─────────────────────────────────────────────────────

def test_cumplimiento_es_entregadas_sobre_no_canceladas(datos):
    # Cumplidas: submitted, approved y closed (3). Esperadas: 9 menos 2 canceladas.
    assert panel(datos)["compliance"] == {"percentage": 42.9, "completed": 3, "expected": 7}


def test_sin_asignaciones_el_cumplimiento_es_nulo(fabrica):
    assert panel(fabrica)["compliance"] == {"percentage": None, "completed": 0, "expected": 0}


# ── Ruta y permisos ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("rol", ["admin", "coordinator", "authority", "auditor"])
def test_los_roles_con_permiso_de_monitoreo_ven_el_panel(datos, rol):
    respuesta = _cliente(datos, _usuario(9, "x@ejemplo.test", rol)).get("/api/v1/dashboard")
    assert respuesta.status_code == 200
    assert respuesta.json()["tasks"]["total"] == 5


@pytest.mark.parametrize("rol", ["teacher", "reviewer"])
def test_docentes_y_revisores_no_ven_el_panel(datos, rol):
    respuesta = _cliente(datos, _usuario(9, "x@ejemplo.test", rol)).get("/api/v1/dashboard")
    assert respuesta.status_code == 403


def test_sin_sesion_da_401(sin_sesion):
    assert sin_sesion.get("/api/v1/dashboard").status_code == 401


@pytest.mark.parametrize("limite", [0, 101, "x"])
def test_limite_invalido_da_422(admin, limite):
    assert admin.get(f"/api/v1/dashboard?limit={limite}").status_code == 422


def test_la_ruta_responde_con_el_formato_del_contrato(admin):
    datos = admin.get("/api/v1/dashboard?limit=5").json()
    assert set(datos) == {"generated_at", "due_soon_days", "tasks", "assignments",
                          "overdue", "due_soon", "compliance"}
    assert datos["generated_at"].endswith("Z")
