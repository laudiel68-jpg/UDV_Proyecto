"""Matriz de estados, acciones y roles. ÚNICA fuente de verdad del workflow.

Cada regla dice: desde qué estado, con qué acción, a qué estado, qué roles pueden
ejecutarla y con qué alcance (scope):
    assignee          -> el usuario debe ser el docente de ESA asignación
    task_reviewer     -> si la tarea tiene revisor, SOLO ese revisor; si no tiene revisor,
                         solo coordinación (la dueña de la tarea) o administración
    task_coordinator  -> debe ser quien creó la tarea o su responsable
`unscoped_roles` son roles que quedan exentos del alcance (p. ej. la autoridad
puede aprobar aunque no sea el revisor designado).
"""
from dataclasses import dataclass

COORDINATOR, TEACHER, REVIEWER, AUTHORITY, SYSTEM, ADMIN = (
    "coordinator", "teacher", "reviewer", "authority", "system", "admin")
ROLES = (COORDINATOR, TEACHER, REVIEWER, AUTHORITY, SYSTEM, ADMIN)

STATES = ("draft", "assigned", "in_progress", "submitted", "under_review",
          "returned", "approved", "closed", "cancelled")
ACTIONS = ("publish", "start", "submit", "review", "return",
           "resubmit", "approve", "close", "cancel")


@dataclass(frozen=True)
class Rule:
    from_state: str
    action: str
    to_state: str
    roles: frozenset
    scope: str = None
    unscoped_roles: frozenset = frozenset()
    comment_required: bool = False


def _r(frm, action, to, roles, scope=None, unscoped=(), comment=False):
    return Rule(frm, action, to, frozenset(roles), scope, frozenset(unscoped), comment)


# Flujo principal: exactamente la tabla mínima del documento.
STANDARD = (
    _r("draft",        "publish",  "assigned",     [COORDINATOR],           "task_coordinator"),
    _r("assigned",     "start",    "in_progress",  [TEACHER],               "assignee"),
    _r("in_progress",  "submit",   "submitted",    [TEACHER],               "assignee"),
    # review y return: el revisor designado; si la tarea NO tiene revisor_id, coordinación o admin
    # (transitions.authorize aplica la regla; con revisor_id solo puede el designado).
    _r("submitted",    "review",   "under_review", [REVIEWER, COORDINATOR, ADMIN], "task_reviewer"),
    _r("under_review", "return",   "returned",     [REVIEWER, COORDINATOR, ADMIN], "task_reviewer", comment=True),
    _r("returned",     "resubmit", "submitted",    [TEACHER],               "assignee"),
    _r("under_review", "approve",  "approved",     [REVIEWER, AUTHORITY],   "task_reviewer", unscoped=[AUTHORITY]),
    _r("approved",     "close",    "closed",       [COORDINATOR, SYSTEM],   "task_coordinator", unscoped=[SYSTEM]),
    _r("draft",        "cancel",   "cancelled",    [COORDINATOR],           "task_coordinator"),
    _r("assigned",     "cancel",   "cancelled",    [COORDINATOR],           "task_coordinator"),
)

# Flujo corto (p. ej. "Confirmar actividad"). SUPUESTO a confirmar con el profesor:
# el docente entrega directo desde assigned y se aprueba sin pasar por revisión.
SHORT = tuple(r for r in STANDARD if r.action in ("publish", "close", "cancel")) + (
    _r("assigned",  "submit",  "submitted", [TEACHER],             "assignee"),
    _r("submitted", "approve", "approved",  [REVIEWER, AUTHORITY], "task_reviewer", unscoped=[AUTHORITY]),
)


def _index(rules):
    return {(r.from_state, r.action): r for r in rules}


FLOWS = {"standard": _index(STANDARD), "short": _index(SHORT)}


def _by_action(rules):
    """Agrupa las reglas por acción (sin importar el estado de origen)."""
    out = {}
    for r in rules:
        out.setdefault(r.action, []).append(r)
    return out


# Permite saber QUIÉN puede ejecutar una acción en un flujo sin depender del estado
# actual. transitions.perform() lo usa para responder 403 antes que 409.
BY_ACTION = {"standard": _by_action(STANDARD), "short": _by_action(SHORT)}


def render_markdown() -> str:
    """Genera la matriz documentada (docs/matriz_estados.md)."""
    names = {COORDINATOR: "Coordinador", TEACHER: "Docente", REVIEWER: "Revisor",
             AUTHORITY: "Autoridad", SYSTEM: "Sistema", ADMIN: "Administrador"}
    scopes = {"assignee": "solo el docente destinatario",
              "task_reviewer": "el revisor designado (sin revisor: solo coordinación o administración, si la fila las incluye)",
              "task_coordinator": "quien creó la tarea o su responsable", None: "-"}
    out = ["# Matriz de estados, acciones y roles", "",
           "Generada desde `workflow/matrix.py`. No editar a mano: ejecutar "
           "`python -m workflow.matrix`.", ""]
    for flow, rules in (("standard", STANDARD), ("short", SHORT)):
        out += [f"## Flujo `{flow}`", "",
                "| Estado actual | Acción | Estado nuevo | Roles | Alcance | Comentario |",
                "| --- | --- | --- | --- | --- | --- |"]
        for r in rules:
            roles = ", ".join(names[x] for x in ROLES if x in r.roles)
            out.append(f"| {r.from_state} | {r.action} | {r.to_state} | {roles} | "
                       f"{scopes[r.scope]} | {'obligatorio' if r.comment_required else '-'} |")
        out.append("")
    out += ["## Orden de validación y códigos de error", "",
            "Las validaciones se hacen siempre en este orden y la primera que falla corta el proceso:", "",
            "1. La asignación no existe: **404**.",
            "2. El usuario no tiene permiso para la acción (rol no permitido, o no es el "
            "destinatario / revisor / coordinador que corresponde): **403**.",
            "3. El estado actual no permite la acción (cualquier combinación estado/acción "
            "que no esté en la tabla): **409**.",
            "4. Falta el comentario obligatorio (p. ej. `return` sin comentario): **422**.", "",
            "Por eso un usuario sin permiso recibe **403 aunque además la transición sea inválida**: "
            "así no se le revela en qué estado está una asignación que no puede tocar.",
            "Si la acción ni siquiera existe en el flujo de la tarea (p. ej. `start` en el flujo `short`), "
            "no hay permisos que evaluar y la respuesta es **409**.",
            "Todo rechazo ocurre antes de escribir, así que nunca modifica datos.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    import pathlib
    path = pathlib.Path(__file__).resolve().parent.parent / "docs" / "matriz_estados.md"
    path.parent.mkdir(parents=True, exist_ok=True)      # antes fallaba si docs/ no existía
    path.write_text(render_markdown(), encoding="utf-8")
    print(f"Escrito {path}")