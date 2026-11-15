"""Capa HTTP (FastAPI). Delgada: solo traduce HTTP <-> funciones del dominio.

Expone un `router` (APIRouter con prefijo /api/v1) que el main.py de la raíz monta con
`app.include_router(router)`. Este módulo NO crea su propia app.

- El usuario sale del token de G2 (ver auth.py), no de headers.
- Errores con el formato del CONTRATO_COMUN: {"error": {"code", "message", "details"}}.
- Paginación: {"page": 1, "per_page": 20, "total": 0, "data": [...]}
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel

from . import events, tasks, transitions
from .auth import current_user
from .deps import get_conn
from .errors import NotFound, WorkflowError
from .http_errors import validation_body
from .matrix import SHORT, STANDARD

PREFIX = "/api/v1"

# Las 6 acciones de asignación que ahora son de G3 (antes las hacía G4).
ASSIGNMENT_ACTIONS = ("start", "submit", "resubmit", "review", "return", "approve")


def _codigo_mayusculas(body):
    """El CONTRATO_COMUN pide los códigos de error en MAYÚSCULAS (INVALID_TRANSITION)."""
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict) and isinstance(err.get("code"), str):
        err["code"] = err["code"].upper()
    return body


class FormatoErrorRoute(APIRoute):
    """Convierte los errores de dominio y de validación al formato del CONTRATO_COMUN, sin
    depender de manejadores registrados en la app de la raíz."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except WorkflowError as exc:
                return JSONResponse(_codigo_mayusculas(exc.to_dict()), status_code=exc.status_code)
            except RequestValidationError as exc:
                return JSONResponse(_codigo_mayusculas(validation_body(exc)), status_code=422)

        return handler


router = APIRouter(prefix=PREFIX, route_class=FormatoErrorRoute)


# ---------------------------------------------------------------- esquemas
class TaskTypeIn(BaseModel):
    code: str
    name: str
    requires_evidence: bool = False
    evidence_type: Optional[str] = None
    flow: str = "standard"


class TaskIn(BaseModel):
    type_id: int
    title: str
    description: str = ""
    priority: str = "medium"
    due_date: str
    responsible_id: Optional[int] = None
    reviewer_id: Optional[int] = None


class TaskPatch(BaseModel):
    type_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    responsible_id: Optional[int] = None
    reviewer_id: Optional[int] = None


class RecipientsIn(BaseModel):
    mode: str                       # users | all | filter
    user_ids: Optional[list[int]] = None
    campus: Optional[str] = None
    unit: Optional[str] = None


class ActionIn(BaseModel):
    comment: Optional[str] = None


class CancelIn(BaseModel):
    reason: Optional[str] = None


# ------------------------------------------------------------- task types
@router.get("/task-types", tags=["task-types"])
def get_task_types(page: int = Query(1), per_page: int = Query(20),
                   conn=Depends(get_conn), user=Depends(current_user)):
    return tasks.list_task_types(conn, page, per_page)


@router.post("/task-types", status_code=201, tags=["task-types"])
def post_task_type(body: TaskTypeIn, conn=Depends(get_conn), user=Depends(current_user)):
    return tasks.create_task_type(conn, user, body.model_dump())


# ------------------------------------------------------------------ tasks
@router.get("/tasks", tags=["tasks"])
def get_tasks(status: Optional[str] = None, page: int = Query(1),
              per_page: int = Query(20), conn=Depends(get_conn),
              user=Depends(current_user)):
    return tasks.list_tasks(conn, user, status, page, per_page)


@router.post("/tasks", status_code=201, tags=["tasks"])
def post_task(body: TaskIn, conn=Depends(get_conn), user=Depends(current_user)):
    return tasks.create_task(conn, user, body.model_dump())


@router.get("/tasks/{task_id}", tags=["tasks"])
def get_task(task_id: int, conn=Depends(get_conn), user=Depends(current_user)):
    return tasks.get_task(conn, user, task_id)


@router.patch("/tasks/{task_id}", tags=["tasks"])
def patch_task(task_id: int, body: TaskPatch, conn=Depends(get_conn),
               user=Depends(current_user)):
    return tasks.update_task(conn, user, task_id, body.model_dump(exclude_unset=True))


@router.post("/tasks/{task_id}/recipients", tags=["tasks"])
def post_recipients(task_id: int, body: RecipientsIn, conn=Depends(get_conn),
                    user=Depends(current_user)):
    return tasks.set_recipients(conn, user, task_id, body.model_dump(exclude_none=True))


@router.post("/tasks/{task_id}/publish", tags=["tasks"])
def post_publish(task_id: int, conn=Depends(get_conn), user=Depends(current_user)):
    return tasks.publish_task(conn, user, task_id)


@router.post("/tasks/{task_id}/cancel", tags=["tasks"])
def post_cancel(task_id: int, body: CancelIn = CancelIn(), conn=Depends(get_conn),
                user=Depends(current_user)):
    return tasks.cancel_task(conn, user, task_id, body.reason)


@router.get("/tasks/{task_id}/assignments", tags=["tracking"])
def get_task_assignments(task_id: int, status: Optional[str] = None,
                         page: int = Query(1), per_page: int = Query(20),
                         conn=Depends(get_conn), user=Depends(current_user)):
    return tasks.list_task_assignments(conn, user, task_id, status, page, per_page)


# ------------------------------------------------------------ assignments



@router.get("/assignments/{assignment_id}/history", tags=["assignments"])
def get_history(assignment_id: int, conn=Depends(get_conn), user=Depends(current_user)):
    return {"items": tasks.get_history(conn, user, assignment_id)}


def _action_endpoint(action: str):
    """POST /assignments/{id}/<acción>. Orden de errores (lo decide transitions.perform):
    404 -> 403 -> 409 -> 422."""
    def endpoint(assignment_id: int, body: ActionIn = ActionIn(),
                 conn=Depends(get_conn), user=Depends(current_user)):
        return transitions.perform(conn, assignment_id, action, user, body.comment)
    endpoint.__name__ = f"post_assignment_{action}"
    return endpoint


for _action in ASSIGNMENT_ACTIONS:
    router.add_api_route(f"/assignments/{{assignment_id}}/{_action}", _action_endpoint(_action),
                         methods=["POST"], tags=["assignments"])


@router.post("/assignments/{assignment_id}/actions/{action}", tags=["assignments"],
             deprecated=True)
def post_action(assignment_id: int, action: str, body: ActionIn = ActionIn(),
                conn=Depends(get_conn), user=Depends(current_user)):
    """Ruta genérica anterior; se mantiene para `close` y `cancel`, que no tienen ruta propia.
    Para las 6 acciones del contrato usar /assignments/{id}/<acción>."""
    return transitions.perform(conn, assignment_id, action, user, body.comment)


# ------------------------------------------------------- eventos y matriz
@router.get("/events", tags=["events"])
def get_events(after_id: int = Query(0), limit: int = Query(100, ge=1, le=500),
               conn=Depends(get_conn), user=Depends(current_user)):
    if user["role"] not in ("authority", "system"):
        raise NotFound("Recurso no disponible para tu rol")      # lo consume el Grupo 6
    return {"items": events.list_events(conn, after_id, limit)}


@router.get("/workflow/matrix", tags=["workflow"])
def get_matrix():
    def dump(rules):
        return [{"from": r.from_state, "action": r.action, "to": r.to_state,
                 "roles": sorted(r.roles), "scope": r.scope,
                 "comment_required": r.comment_required} for r in rules]
    return {"standard": dump(STANDARD), "short": dump(SHORT)}