"""Auditoría transversal (escenarios G6-14, G6-15 y G6-30 a G6-33).

Cada acción importante deja un registro con quién la hizo, cuándo, sobre qué
entidad y qué cambió. Los registros solo se agregan: no hay forma de editarlos
ni de borrarlos (CONTRATO_COMUN.md §1, "Auditoría").

Las transiciones de estado (G6-15) las reportan el G3 (tareas y asignaciones)
y el G5 (versiones de programa); los cambios de catálogos los registra el
propio G6. Este archivo NO importa FastAPI, igual que catalogos.py.
"""

import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from .errores import validacion
from .paginacion import PER_PAGE_PREDETERMINADO, paginar
from .seguridad import Usuario, exigir_administrador

# Estados oficiales (CONTRATO_COMUN.md §2). Una transición solo se acepta con
# estados de esta lista, para que el historial no guarde nombres inventados.
ESTADOS_TAREA = frozenset({"draft", "assigned", "in_progress", "submitted",
                           "under_review", "returned", "approved", "closed",
                           "cancelled"})
ESTADOS_PROGRAMA = frozenset({"draft", "submitted", "under_review", "returned",
                              "approved", "authorized", "superseded"})
ESTADOS_POR_ENTIDAD: dict[str, frozenset[str]] = {
    "task": ESTADOS_TAREA,
    "assignment": ESTADOS_TAREA,
    "program_version": ESTADOS_PROGRAMA,
}

ACCION_TRANSICION = "transition"
TEXTO_MAXIMO = 120
COMENTARIO_MAXIMO = 1000


@dataclass(frozen=True)
class RegistroAuditoria:
    id: int
    actor_id: int
    accion: str
    entidad: str
    entidad_id: int
    fecha: str
    estado_anterior: str | None = None
    estado_nuevo: str | None = None
    comentario: str | None = None
    cambios: dict[str, Any] = field(default_factory=dict)

    def como_dict(self) -> dict[str, Any]:
        return {"id": self.id, "actor_id": self.actor_id, "action": self.accion,
                "entity": self.entidad, "entity_id": self.entidad_id,
                "created_at": self.fecha, "from_state": self.estado_anterior,
                "to_state": self.estado_nuevo, "comment": self.comentario,
                "changes": dict(self.cambios)}


class RepositorioAuditoriaEnMemoria:
    """Guarda la auditoría en memoria mientras el G1 entrega la tabla.

    Solo tiene agregar y listar a propósito: el repositorio con MySQL debe
    tener los mismos dos métodos y ningún UPDATE ni DELETE sobre la tabla.
    """

    def __init__(self) -> None:
        self._registros: list[RegistroAuditoria] = []
        self._siguiente_id = 1
        self._candado = threading.Lock()

    def agregar(self, **datos: Any) -> RegistroAuditoria:
        with self._candado:
            registro = RegistroAuditoria(
                id=self._siguiente_id,
                fecha=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **datos)
            self._siguiente_id += 1
            self._registros.append(registro)
            return registro

    def listar(self) -> list[RegistroAuditoria]:
        with self._candado:
            return list(self._registros)


def _es_entero_positivo(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool) and valor > 0


def _texto(valor: Any) -> bool:
    return isinstance(valor, str) and bool(valor.strip()) and len(valor) <= TEXTO_MAXIMO


class ServicioAuditoria:
    def __init__(self, repositorio: RepositorioAuditoriaEnMemoria) -> None:
        self.repositorio = repositorio

    def registrar(self, *, actor_id: Any, accion: Any, entidad: Any,
                  entidad_id: Any, cambios: dict[str, Any] | None = None) -> dict[str, Any]:
        """Registra una acción que no es transición (G6-14), como crear un registro."""
        errores = self._validar_basico(actor_id, accion, entidad, entidad_id)
        if accion == ACCION_TRANSICION:
            errores["action"] = "Para una transición usa registrar_transicion."
        if cambios is not None and not isinstance(cambios, dict):
            errores["changes"] = "Envía los cambios como objeto."
        if errores:
            raise validacion(errores)
        return self.repositorio.agregar(
            actor_id=actor_id, accion=accion.strip(), entidad=entidad.strip(),
            entidad_id=entidad_id, cambios=dict(cambios or {})).como_dict()

    def registrar_transicion(self, *, actor_id: Any, entidad: Any, entidad_id: Any,
                             estado_anterior: Any, estado_nuevo: Any,
                             comentario: Any = "") -> dict[str, Any]:
        """Registra un cambio de estado con lo que pide el contrato común (G6-15).

        El G3 y el G5 la llaman dentro de la misma operación que cambia el
        estado, para que no quede una transición sin su registro.
        """
        errores = self._validar_basico(actor_id, ACCION_TRANSICION, entidad, entidad_id)
        estados = ESTADOS_POR_ENTIDAD.get(entidad) if isinstance(entidad, str) else None
        if "entity" not in errores and estados is None:
            errores["entity"] = ("Entidad sin estados oficiales. Usa: "
                                 + ", ".join(sorted(ESTADOS_POR_ENTIDAD)) + ".")
        if estados is not None:
            if estado_anterior not in estados:
                errores["from_state"] = "Estado no reconocido para esta entidad."
            if estado_nuevo not in estados:
                errores["to_state"] = "Estado no reconocido para esta entidad."
            elif estado_nuevo == estado_anterior:
                errores["to_state"] = "El estado nuevo debe ser distinto del anterior."
        if not isinstance(comentario, str) or len(comentario) > COMENTARIO_MAXIMO:
            errores["comment"] = f"Debe ser texto de hasta {COMENTARIO_MAXIMO} caracteres."
        if errores:
            raise validacion(errores)
        return self.repositorio.agregar(
            actor_id=actor_id, accion=ACCION_TRANSICION, entidad=entidad,
            entidad_id=entidad_id, estado_anterior=estado_anterior,
            estado_nuevo=estado_nuevo, comentario=comentario.strip()).como_dict()

    @staticmethod
    def _validar_basico(actor_id: Any, accion: Any, entidad: Any,
                        entidad_id: Any) -> dict[str, str]:
        errores: dict[str, str] = {}
        if not _es_entero_positivo(actor_id):
            errores["actor_id"] = "Debe ser el id del usuario que hizo la acción."
        if not _texto(accion):
            errores["action"] = "Campo obligatorio."
        if not _texto(entidad):
            errores["entity"] = "Campo obligatorio."
        if not _es_entero_positivo(entidad_id):
            errores["entity_id"] = "Debe ser un número entero positivo."
        return errores

    def consultar(self, usuario: Usuario, *, actor_id: int | None = None,
                  desde: date | None = None, hasta: date | None = None,
                  entidad: str | None = None, accion: str | None = None,
                  page: int = 1, per_page: int = PER_PAGE_PREDETERMINADO) -> dict[str, Any]:
        """Consulta filtrada, de lo más reciente a lo más antiguo (G6-30 a G6-33).

        Solo administración: la auditoría muestra lo que hizo cada persona.
        Las fechas incluyen el día completo, en UTC.
        """
        exigir_administrador(usuario, "consultar la auditoría")
        if desde and hasta and desde > hasta:
            raise validacion({"to": "Debe ser igual o posterior a la fecha inicial."})

        registros = self.repositorio.listar()
        if actor_id is not None:
            registros = [r for r in registros if r.actor_id == actor_id]
        if entidad:
            registros = [r for r in registros if r.entidad == entidad.strip()]
        if accion:
            registros = [r for r in registros if r.accion == accion.strip()]
        if desde:
            registros = [r for r in registros if r.fecha[:10] >= desde.isoformat()]
        if hasta:
            registros = [r for r in registros if r.fecha[:10] <= hasta.isoformat()]

        registros.sort(key=lambda r: r.id, reverse=True)
        return paginar([r.como_dict() for r in registros], page, per_page)
