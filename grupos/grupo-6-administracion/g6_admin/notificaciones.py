"""Notificaciones internas (escenarios G6-04 a G6-13 y G6-17).

Los grupos 3, 4 y 5 no llaman al G6: cuando cambian una tarea, una entrega o
un programa, los triggers del G1 dejan una fila en la tabla `evento`
(task.published, assignment.submitted, ..., program.authorized). El G6 toma
los eventos pendientes, decide a quién avisar leyendo las tablas y guarda una
notificación por destinatario (G6-17). Aquí vive esa lógica: qué eventos
existen, qué datos lleva cada aviso, cómo se evita duplicar y quién puede
marcar una notificación como leída.

Quién inició sesión lo decide api.py con el middleware del G2. Los errores
salen con el formato común del G2 (g2_api.middleware.error_handler).
"""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from g2_api.middleware.error_handler import ErrorCode, api_error
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.orm import Session

from . import tablas

log = logging.getLogger("g6_admin.notificaciones")


@dataclass(frozen=True)
class TipoEvento:
    nombre: str
    campos: tuple[str, ...]  # Datos que necesita el mensaje
    titulo: str              # notificacion.titulo
    plantilla: str           # Mensaje que ve el destinatario


# Los mismos siete nombres que acepta la tabla evento del G1
# (CHECK ck_evento_nombre) y la tabla del CONTRATO.md §3.
EVENTOS: dict[str, TipoEvento] = {e.nombre: e for e in (
    TipoEvento("task.published", ("task_title", "due_date"), "Nueva tarea asignada",
               "Nueva tarea asignada: «{task_title}». Fecha límite: {due_date}."),
    TipoEvento("assignment.due_soon", ("task_title", "due_date"), "Tarea por vencer",
               "La tarea «{task_title}» vence el {due_date}."),
    TipoEvento("assignment.submitted", ("task_title",), "Nueva entrega",
               "Hay una entrega de «{task_title}» lista para revisión."),
    TipoEvento("assignment.returned", ("task_title", "comment"), "Entrega devuelta",
               "Tu entrega de «{task_title}» fue devuelta. Observación: {comment}"),
    TipoEvento("assignment.approved", ("task_title",), "Entrega aprobada",
               "La entrega de «{task_title}» fue aprobada."),
    TipoEvento("program.authorized", ("program_name",), "Programa autorizado",
               "Se autorizó una nueva versión del programa «{program_name}»."),
    TipoEvento("task.cancelled", ("task_title",), "Tarea cancelada",
               "La tarea «{task_title}» fue cancelada."),
)}

TEXTO_MAXIMO = 500
CLAVE_MAXIMA = 120  # evento.clave_unica es VARCHAR(120)
ROL_COORDINACION = "coordinator"


def _ahora() -> datetime:
    # Sin zona: las columnas son DATETIME y el G1 guarda todo en UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(valor: datetime | None) -> str | None:
    return None if valor is None else valor.replace(microsecond=0).isoformat() + "Z"


def _fecha_visible(valor: datetime | None) -> str:
    return valor.strftime("%Y-%m-%d %H:%M") + " (UTC)" if valor else "sin fecha límite"


def como_dict(fila: Any) -> dict[str, Any]:
    return {"id": fila.id, "event": fila.tipo, "title": fila.titulo,
            "message": fila.mensaje, "is_read": fila.leida_en is not None,
            "created_at": _iso(fila.creado_en), "read_at": _iso(fila.leida_en)}


class RepositorioNotificaciones:
    """Lee y escribe `evento` y `notificacion` (tablas del G1).

    La tabla notificacion tiene la llave única (evento_id, usuario_id): aunque
    dos peticiones procesen el mismo evento a la vez, la base no deja duplicar.
    """

    def __init__(self, sesion: Session) -> None:
        self.sesion = sesion

    @contextmanager
    def transaccion(self) -> Iterator[None]:
        try:
            yield
            self.sesion.commit()
        except BaseException:
            self.sesion.rollback()
            raise

    # ── eventos ──

    def evento_por_clave(self, clave: str) -> Any | None:
        return self.sesion.execute(select(tablas.evento).where(
            tablas.evento.c.clave_unica == clave)).first()

    def agregar_evento(self, nombre: str, clave: str, payload: dict[str, Any]) -> int:
        resultado = self.sesion.execute(insert(tablas.evento).values(
            nombre=nombre, clave_unica=clave, creado_en=_ahora(),
            payload=json.dumps(payload, ensure_ascii=False)))
        return resultado.inserted_primary_key[0]

    def marcar_procesado(self, evento_id: int) -> None:
        # El G1 solo deja cambiar procesado_en una vez (trigger trg_evento_bu).
        self.sesion.execute(update(tablas.evento).where(
            tablas.evento.c.id == evento_id, tablas.evento.c.procesado_en.is_(None)
        ).values(procesado_en=_ahora()))

    def pendientes(self, limite: int) -> list[Any]:
        return list(self.sesion.execute(
            select(tablas.evento).where(tablas.evento.c.procesado_en.is_(None))
            .order_by(tablas.evento.c.id).limit(limite)))

    def generar_vencimientos(self) -> None:
        """Pide al G1 los eventos assignment.due_soon (procedimiento de MySQL)."""
        if self.sesion.get_bind().dialect.name in ("mysql", "mariadb"):
            self.sesion.execute(text("CALL sp_generar_eventos_vencimiento(@creados)"))

    # ── notificaciones ──

    def ya_avisados(self, evento_id: int) -> set[int]:
        n = tablas.notificacion
        return set(self.sesion.execute(
            select(n.c.usuario_id).where(n.c.evento_id == evento_id)).scalars())

    def agregar_notificaciones(self, filas: list[dict[str, Any]]) -> list[Any]:
        if not filas:
            return []
        ahora = _ahora()
        ids = [self.sesion.execute(insert(tablas.notificacion).values(
            **fila, creado_en=ahora)).inserted_primary_key[0] for fila in filas]
        return list(self.sesion.execute(select(tablas.notificacion).where(
            tablas.notificacion.c.id.in_(ids)).order_by(tablas.notificacion.c.id)))

    def listar_de(self, usuario_id: int, *, no_leidas: bool, pagina: int,
                  por_pagina: int) -> tuple[int, list[Any]]:
        n = tablas.notificacion
        condiciones = [n.c.usuario_id == usuario_id]
        if no_leidas:
            condiciones.append(n.c.leida_en.is_(None))
        total = self.sesion.execute(
            select(func.count()).select_from(n).where(*condiciones)).scalar_one()
        filas = self.sesion.execute(
            select(n).where(*condiciones).order_by(n.c.id.desc())
            .limit(por_pagina).offset((pagina - 1) * por_pagina))
        return total, list(filas)

    def marcar_leida(self, notificacion_id: int, usuario_id: int) -> Any | None:
        """Marca solo si la notificación es de ese usuario; si no, devuelve None."""
        n = tablas.notificacion
        propia = (n.c.id == notificacion_id) & (n.c.usuario_id == usuario_id)
        self.sesion.execute(update(n).where(propia, n.c.leida_en.is_(None))
                            .values(leida_en=_ahora()))
        return self.sesion.execute(select(n).where(propia)).first()

    # ── lo que se lee de las tablas de G3, G4 y G5 para armar el aviso ──

    def tarea(self, tarea_id: int | None) -> Any | None:
        if tarea_id is None:
            return None
        return self.sesion.execute(select(tablas.tarea).where(
            tablas.tarea.c.id == tarea_id)).first()

    def asignacion(self, asignacion_id: int | None) -> Any | None:
        if asignacion_id is None:
            return None
        return self.sesion.execute(select(tablas.tarea_destinatario).where(
            tablas.tarea_destinatario.c.id == asignacion_id)).first()

    def destinatarios_de_tarea(self, tarea_id: int) -> list[int]:
        td = tablas.tarea_destinatario
        return list(self.sesion.execute(
            select(td.c.usuario_id).where(td.c.tarea_id == tarea_id)
            .order_by(td.c.id)).scalars())

    def programa(self, version_id: int | None) -> Any | None:
        if version_id is None:
            return None
        return self.sesion.execute(select(tablas.programa_version).where(
            tablas.programa_version.c.id == version_id)).first()

    def con_rol(self, codigo_rol: str) -> list[int]:
        u, ur, r = tablas.usuario, tablas.usuario_rol, tablas.rol
        return list(self.sesion.execute(
            select(u.c.id).join(ur, ur.c.usuario_id == u.c.id).join(r, r.c.id == ur.c.rol_id)
            .where(r.c.codigo == codigo_rol, r.c.activo.is_(True), u.c.activo.is_(True))
            .order_by(u.c.id)).scalars())


def _error_de_campo(campo: str, codigo: str, mensaje: str) -> dict[str, str]:
    # Misma forma que usa el G2 para el detalle de un 422.
    return {"field": campo, "code": codigo, "message": mensaje}


def _es_entero(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def validar_evento(evento: Any) -> tuple[TipoEvento, str, list[int], dict[str, str]]:
    """Revisa un evento {"id", "name", "recipients", "data"} antes de guardar nada."""
    if not isinstance(evento, dict):
        raise api_error(422, ErrorCode.VALIDATION_ERROR, "El evento debe ser un objeto.",
                        [_error_de_campo("_body", "OBJECT_TYPE", "Envía un objeto.")])

    errores: list[dict[str, str]] = []
    tipo = EVENTOS.get(evento.get("name")) if isinstance(evento.get("name"), str) else None
    if tipo is None:
        errores.append(_error_de_campo("name", "UNKNOWN_EVENT", "Evento desconocido."))

    evento_id = evento.get("id")
    if (not isinstance(evento_id, str) or not evento_id.strip()
            or len(evento_id.strip()) > CLAVE_MAXIMA):
        errores.append(_error_de_campo(
            "id", "REQUIRED",
            f"Cada evento necesita un identificador único (texto de hasta {CLAVE_MAXIMA})."))

    destinatarios = evento.get("recipients")
    if (not isinstance(destinatarios, list) or not destinatarios
            or not all(_es_entero(u) and u > 0 for u in destinatarios)):
        errores.append(_error_de_campo(
            "recipients", "INVALID", "Envía una lista con los id de los destinatarios."))

    datos = evento.get("data")
    if not isinstance(datos, dict):
        errores.append(_error_de_campo("data", "OBJECT_TYPE",
                                       "Envía los datos del evento como objeto."))
        datos = {}
    if tipo is not None:
        for campo in tipo.campos:
            valor = datos.get(campo)
            if not isinstance(valor, str) or not valor.strip():
                errores.append(_error_de_campo(f"data.{campo}", "REQUIRED",
                                               "Campo obligatorio."))
            elif len(valor) > TEXTO_MAXIMO:
                errores.append(_error_de_campo(
                    f"data.{campo}", "TOO_LONG",
                    f"Usa como máximo {TEXTO_MAXIMO} caracteres."))

    if errores:
        raise api_error(422, ErrorCode.VALIDATION_ERROR,
                        "El evento no es válido.", errores)
    limpios = {c: " ".join(datos[c].split()) for c in tipo.campos}
    # dict.fromkeys quita destinatarios repetidos conservando el orden.
    return tipo, evento_id.strip(), list(dict.fromkeys(destinatarios)), limpios


class ServicioNotificaciones:
    def __init__(self, repositorio: RepositorioNotificaciones) -> None:
        self.repositorio = repositorio

    def _avisar(self, evento_id: int, tipo: TipoEvento, destinatarios: list[int],
                datos: dict[str, str], referencias: dict[str, Any]) -> list[Any]:
        """Guarda una notificación por destinatario que aún no tenga la suya."""
        mensaje = tipo.plantilla.format(**datos)[:1000]
        ya = self.repositorio.ya_avisados(evento_id)
        return self.repositorio.agregar_notificaciones([
            {"usuario_id": u, "tipo": tipo.nombre, "titulo": tipo.titulo,
             "mensaje": mensaje, "evento_id": evento_id, **referencias}
            for u in destinatarios if u not in ya])

    def procesar_evento(self, evento: Any) -> list[dict[str, Any]]:
        """Crea las notificaciones de un evento que llega armado {"id", "name", ...}.

        Sirve para eventos que no salen de un trigger del G1. Procesar dos
        veces el mismo evento (mismo "id") no duplica nada (G6-11). Todo queda
        guardado o nada (G6-18). Devuelve solo las notificaciones nuevas.
        """
        tipo, clave, destinatarios, datos = validar_evento(evento)
        with self.repositorio.transaccion():
            fila = self.repositorio.evento_por_clave(clave)
            if fila is not None and fila.nombre != tipo.nombre:
                raise api_error(409, ErrorCode.CONFLICT,
                                "Ese id ya se usó para otro evento.")
            evento_id = fila.id if fila is not None else self.repositorio.agregar_evento(
                tipo.nombre, clave, {"recipients": destinatarios, "data": datos})
            nuevas = self._avisar(evento_id, tipo, destinatarios, datos, {})
            self.repositorio.marcar_procesado(evento_id)
            return [como_dict(n) for n in nuevas]

    # ── G6-17: eventos que dejan los triggers del G1 ──

    def _armar(self, fila: Any) -> tuple[list[int], dict[str, str], dict[str, Any]]:
        """A quién avisar y con qué datos, leyendo las tablas (CONTRATO.md §3)."""
        repo = self.repositorio
        payload = json.loads(fila.payload) if fila.payload else {}
        asignacion = repo.asignacion(fila.tarea_destinatario_id)
        tarea = repo.tarea(fila.tarea_id or (asignacion.tarea_id if asignacion else None))
        datos: dict[str, str] = {}
        referencias: dict[str, Any] = {}
        if tarea is not None:
            datos["task_title"] = tarea.titulo
            limite = (asignacion.fecha_limite if asignacion and asignacion.fecha_limite
                      else tarea.fecha_limite)
            datos["due_date"] = _fecha_visible(limite)
        if asignacion is not None:
            referencias["tarea_destinatario_id"] = asignacion.id

        nombre = fila.nombre
        if nombre in ("task.published", "task.cancelled") and tarea is not None:
            destinatarios = repo.destinatarios_de_tarea(tarea.id)
        elif nombre in ("assignment.due_soon", "assignment.returned") and asignacion:
            destinatarios = [asignacion.usuario_id]
            datos["comment"] = (payload.get("comentario") or "").strip() or "Sin comentario."
        elif nombre == "assignment.submitted" and asignacion:
            revisor = asignacion.revisor_id or (tarea.revisor_id if tarea else None)
            destinatarios = [revisor] if revisor else []
        elif nombre == "assignment.approved" and asignacion:
            # Docente y coordinador (quien creó la tarea).
            destinatarios = [asignacion.usuario_id] + ([tarea.creado_por] if tarea else [])
        elif nombre == "program.authorized":
            programa = repo.programa(fila.programa_version_id)
            if programa is None:
                return [], {}, {}
            datos["program_name"] = programa.nombre
            referencias["programa_version_id"] = programa.id
            docente = programa.docente_responsable_id or programa.creado_por
            destinatarios = [docente] + repo.con_rol(ROL_COORDINACION)
        else:
            destinatarios = []
        return [u for u in dict.fromkeys(destinatarios) if u], datos, referencias

    def procesar_pendientes(self, limite: int = 200) -> dict[str, int]:
        """Convierte en notificaciones los eventos que aún no se procesaron (G6-17).

        Cada evento va en su propia transacción: si uno falla, no deja nada a
        medias y los demás siguen (G6-18). Se puede llamar las veces que sea:
        lo ya procesado no se repite.
        """
        resumen = {"processed": 0, "notifications": 0, "failed": 0}
        try:
            with self.repositorio.transaccion():
                self.repositorio.generar_vencimientos()
        except Exception as exc:  # El aviso de vencimiento no debe frenar los demás.
            log.warning("No se generaron los eventos de vencimiento: %s", type(exc).__name__)

        for fila in self.repositorio.pendientes(limite):
            try:
                with self.repositorio.transaccion():
                    tipo = EVENTOS[fila.nombre]
                    destinatarios, datos, referencias = self._armar(fila)
                    faltan = [c for c in tipo.campos if c not in datos]
                    nuevas = [] if faltan or not destinatarios else self._avisar(
                        fila.id, tipo, destinatarios, datos, referencias)
                    if faltan or not destinatarios:
                        log.warning("Evento %s sin destinatarios o sin datos; se marca procesado",
                                    fila.id)
                    self.repositorio.marcar_procesado(fila.id)
                resumen["processed"] += 1
                resumen["notifications"] += len(nuevas)
            except Exception as exc:
                resumen["failed"] += 1
                log.error("No se pudo procesar el evento %s: %s", fila.id, type(exc).__name__)
        return resumen

    # ── consulta del usuario ──

    def listar(self, usuario_id: int, *, no_leidas: bool = False, pagina: int = 1,
               por_pagina: int = 20) -> tuple[int, list[dict[str, Any]]]:
        """Solo las del usuario, de la más reciente a la más antigua."""
        total, filas = self.repositorio.listar_de(
            usuario_id, no_leidas=no_leidas, pagina=pagina, por_pagina=por_pagina)
        return total, [como_dict(f) for f in filas]

    def marcar_leida(self, usuario_id: int, notificacion_id: int) -> dict[str, Any]:
        """Marca como leída una notificación propia (G6-12 y G6-13).

        La de otra persona responde 404, igual que una inexistente, para no
        revelar qué notificaciones existen.
        """
        with self.repositorio.transaccion():
            fila = self.repositorio.marcar_leida(notificacion_id, usuario_id)
        if fila is None:
            raise api_error(404, ErrorCode.NOT_FOUND, "No existe esa notificación.")
        return como_dict(fila)
