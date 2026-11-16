"""Reglas para saber en qué paso va cada versión del programa.

Los estados indican qué sigue: ``draft`` es un borrador editable; ``submitted``
espera a Coordinación o revisión; ``under_review`` está en revisión; ``returned``
vuelve al docente para corregirlo; ``approved`` espera a Dirección;
``authorized`` es la versión vigente; y ``superseded`` ya fue reemplazada.

El recorrido normal es ``draft`` o ``returned`` -> ``submitted`` ->
``under_review`` -> ``approved`` -> ``authorized``. Si hace falta corregir
algo, desde ``under_review`` se puede volver a ``returned``. Cuando se autoriza
una nueva versión, la base puede marcar la anterior como ``superseded``.
"""

from .errors import ApiError

TRANSITIONS = {
    "submit": {"draft": "submitted", "returned": "submitted"},
    "review": {"submitted": "under_review"},
    "return": {"under_review": "returned"},
    "approve": {"under_review": "approved"},
}

ACTOR_ROLES = {
    "submit": "author",
    "review": "reviewer",
    "return": "reviewer",
    "approve": "reviewer",
    "authorize": "authority",
}

def editable(status: str) -> None:
    """Permite editar solo borradores y versiones que volvieron para corrección."""
    if status not in {"draft", "returned"}:
        raise ApiError(409, "CONFLICT", "Solo se puede editar una versión draft o returned.")


def next_status(action: str, current: str) -> str:
    """Indica a qué estado pasa la versión o avisa si el cambio no está permitido.

    La autorización solo va de ``approved`` a ``authorized``. Las demás rutas
    posibles están anotadas en ``TRANSITIONS``.
    """
    if action == "authorize":
        expected = "approved"
        if current == expected:
            return "authorized"
    else:
        destination = TRANSITIONS.get(action, {}).get(current)
        if destination:
            return destination
    raise ApiError(
        409,
        "CONFLICT",
        f"No se puede ejecutar {action} desde el estado '{current}'.",
    )


def ensure_single_authorized(versions: list[dict], program_course_id: int, period_id: int) -> None:
    """Comprueba que el curso y período no tengan dos versiones vigentes."""
    authorized = [
        version for version in versions
        if version.get("programa_curso_id", program_course_id) == program_course_id
        and version.get("periodo_id", period_id) == period_id
        and version.get("estado_codigo", "authorized") == "authorized"
    ]
    if len(authorized) > 1:
        raise ApiError(409, "CONFLICT", "El curso ya tiene más de una versión autorizada.")
