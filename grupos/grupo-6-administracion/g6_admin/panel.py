"""Panel de indicadores (escenarios G6-26 a G6-29).

Todo se calcula en el momento con las tablas del G1, sin copias ni tablas
propias, para que el panel coincida con lo que hay en la base (CONTRATO.md del
G6 §4). Las reglas son las mismas de la vista `v_panel_tarea` del G1:

- Fecha límite de una asignación: la suya, o si no tiene, la de su tarea.
- Vencida: la fecha límite ya pasó y la asignación sigue pendiente
  (assigned, in_progress o returned).
- Próxima a vencer: pendiente y vence en los próximos N días; N es el
  parámetro `dias_aviso_vencimiento` del G1 (3 en la semilla).
- Cumplimiento: asignaciones entregadas o aprobadas (submitted, under_review,
  approved o closed) sobre todas las que no se cancelaron.
- Las tareas con eliminación lógica (`eliminado_en`) no cuentan.

Una diferencia con la vista: si la tarea ya está cancelada o cerrada, sus
asignaciones no se muestran como vencidas ni próximas, aunque alguna haya
quedado en un estado pendiente (el G1 no cambia las asignaciones al cancelar
la tarea). Ya no hay nada que entregar ahí.

"Ahora" es la hora de la base (NOW(3) en MySQL), la misma con la que el G1
calcula la vista y genera los avisos de vencimiento, y la misma zona en que
guarda sus fechas. Así el panel no cambia si el servidor de la app tiene otra
hora o zona. Las fechas de la respuesta llevan la diferencia de la base con
UTC ("Z" si la base está en UTC). docs/panel.md trae las consultas SQL para
comprobar cada número.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from . import tablas

# Estados oficiales en el orden del flujo (CONTRATO_COMUN.md §2), para
# mostrarlos siempre igual.
ORDEN_ESTADOS = ("draft", "assigned", "in_progress", "submitted", "under_review",
                 "returned", "approved", "closed", "cancelled")

ESTADOS_PENDIENTES = ("assigned", "in_progress", "returned")
ESTADOS_CUMPLIDOS = ("submitted", "under_review", "approved", "closed")
ESTADOS_FINALES_TAREA = ("cancelled", "closed")  # es_final en estado_tarea del G1
DIAS_AVISO_PREDETERMINADO = 3  # El mismo valor de la semilla del G1.


def _iso(valor: datetime | None, desfase: int = 0) -> str | None:
    """Fecha de la base en ISO 8601, con su diferencia con UTC en minutos."""
    if valor is None:
        return None
    texto = valor.replace(microsecond=0).isoformat()
    if desfase == 0:
        return texto + "Z"
    signo = "+" if desfase > 0 else "-"
    horas, minutos = divmod(abs(desfase), 60)
    return f"{texto}{signo}{horas:02d}:{minutos:02d}"


class RepositorioPanel:
    """Consultas de solo lectura sobre tarea, tarea_destinatario y parametro."""

    def __init__(self, sesion: Session) -> None:
        self.sesion = sesion

    def reloj(self) -> tuple[datetime, int]:
        """La hora de la base y su diferencia con UTC, en minutos."""
        if self.sesion.get_bind().dialect.name == "mysql":
            ahora, utc = self.sesion.execute(text("SELECT NOW(3), UTC_TIMESTAMP(3)")).one()
        else:  # SQLite de las pruebas: CURRENT_TIMESTAMP ya es UTC.
            ahora = utc = self.sesion.execute(select(func.current_timestamp())).scalar_one()
        return ahora, round((ahora - utc).total_seconds() / 60)

    def dias_aviso(self) -> int:
        valor = self.sesion.execute(select(tablas.parametro.c.valor).where(
            tablas.parametro.c.codigo == "dias_aviso_vencimiento")).scalar()
        try:
            dias = int(valor)
        except (TypeError, ValueError):
            return DIAS_AVISO_PREDETERMINADO
        return dias if dias > 0 else DIAS_AVISO_PREDETERMINADO

    def tareas_por_estado(self) -> dict[str, int]:
        t = tablas.tarea
        filas = self.sesion.execute(
            select(t.c.estado_codigo, func.count())
            .where(t.c.eliminado_en.is_(None)).group_by(t.c.estado_codigo))
        return {estado: total for estado, total in filas}

    def asignaciones_por_estado(self) -> dict[str, int]:
        t, td = tablas.tarea, tablas.tarea_destinatario
        filas = self.sesion.execute(
            select(td.c.estado_codigo, func.count())
            .join(t, t.c.id == td.c.tarea_id)
            .where(t.c.eliminado_en.is_(None)).group_by(td.c.estado_codigo))
        return {estado: total for estado, total in filas}

    def pendientes_que_vencen(self, *, desde: datetime | None, hasta: datetime,
                              limite: int) -> tuple[int, list[dict[str, Any]]]:
        """Asignaciones pendientes con fecha límite en [desde, hasta)."""
        t, td, u = tablas.tarea, tablas.tarea_destinatario, tablas.usuario
        vence = func.coalesce(td.c.fecha_limite, t.c.fecha_limite)
        condiciones = [t.c.eliminado_en.is_(None),
                       t.c.estado_codigo.not_in(ESTADOS_FINALES_TAREA),
                       td.c.estado_codigo.in_(ESTADOS_PENDIENTES),
                       vence.is_not(None), vence < hasta]
        if desde is not None:
            condiciones.append(vence >= desde)
        total = self.sesion.execute(
            select(func.count()).select_from(td).join(t, t.c.id == td.c.tarea_id)
            .where(*condiciones)).scalar_one()
        filas = self.sesion.execute(
            select(td.c.id, td.c.tarea_id, t.c.titulo, td.c.usuario_id, u.c.correo,
                   u.c.nombres, u.c.apellidos, td.c.estado_codigo, vence.label("vence"))
            .join(t, t.c.id == td.c.tarea_id)
            .outerjoin(u, u.c.id == td.c.usuario_id)
            .where(*condiciones).order_by(vence, td.c.id).limit(limite))
        return total, [{
            "assignment_id": f.id, "task_id": f.tarea_id, "task_title": f.titulo,
            "user_id": f.usuario_id, "user_email": f.correo,
            "user_name": " ".join(p for p in (f.nombres, f.apellidos) if p) or None,
            "state": f.estado_codigo, "due_date": f.vence} for f in filas]


class ServicioPanel:
    def __init__(self, repositorio: RepositorioPanel) -> None:
        self.repositorio = repositorio

    def indicadores(self, *, limite: int = 20, ahora: datetime | None = None) -> dict[str, Any]:
        """Todo el panel en una respuesta. `limite` corta las listas, no los totales.

        `ahora` solo se pasa en las pruebas; si no, es la hora de la base.
        """
        hora_de_la_base, desfase = self.repositorio.reloj()
        ahora = ahora or hora_de_la_base
        dias = self.repositorio.dias_aviso()
        tareas = self.repositorio.tareas_por_estado()
        asignaciones = self.repositorio.asignaciones_por_estado()

        total_vencidas, vencidas = self.repositorio.pendientes_que_vencen(
            desde=None, hasta=ahora, limite=limite)
        total_proximas, proximas = self.repositorio.pendientes_que_vencen(
            desde=ahora, hasta=ahora + timedelta(days=dias), limite=limite)

        for item in vencidas + proximas:
            item["due_date"] = _iso(item["due_date"], desfase)

        cumplidas = sum(asignaciones.get(e, 0) for e in ESTADOS_CUMPLIDOS)
        esperadas = sum(n for e, n in asignaciones.items() if e != "cancelled")
        return {
            "generated_at": _iso(ahora, desfase),
            "due_soon_days": dias,
            "tasks": _conteo(tareas),
            "assignments": _conteo(asignaciones),
            "overdue": {"total": total_vencidas, "items": vencidas},
            "due_soon": {"total": total_proximas, "items": proximas},
            "compliance": {
                "percentage": round(100 * cumplidas / esperadas, 1) if esperadas else None,
                "completed": cumplidas, "expected": esperadas},
        }


def _conteo(por_estado: dict[str, int]) -> dict[str, Any]:
    # Todos los estados oficiales aparecen, aunque sea con 0. Si la base tuviera
    # uno distinto (no debería), también se muestra para que el total cuadre.
    estados = {e: por_estado.get(e, 0) for e in ORDEN_ESTADOS}
    estados.update({e: n for e, n in por_estado.items() if e not in estados})
    return {"total": sum(estados.values()), "by_state": estados}
