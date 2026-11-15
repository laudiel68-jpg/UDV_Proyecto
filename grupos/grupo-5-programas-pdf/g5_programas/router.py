"""Rutas de la API para trabajar con programas de curso y sus versiones.

Cada ruta comprueba quién está haciendo la solicitud y deja el trabajo de la
base de datos al repositorio. Todas empiezan con ``/api/v1``.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from .auth import Actor, authenticated_actor, has_role, require_role
from .database import get_session
from .domain import ACTOR_ROLES
from . import repository
from .schemas import (
    EncabezadoVersion,
    EvaluacionSeccion,
    ProgramaNuevo,
    ResponsablesSeccion,
    SeccionActualizacion,
    TransicionVersion,
    VersionNueva,
)

router = APIRouter(prefix="/api/v1", tags=["Programas de curso"])
DbSession = Annotated[Session, Depends(get_session)]
CurrentActor = Annotated[Actor, Depends(authenticated_actor)]


# Rutas para consultar y crear programas y versiones.
@router.get("/course-programs")
def list_course_programs(
    session: DbSession,
    actor: CurrentActor,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
    curso_id: Annotated[int | None, Query(ge=1)] = None,
    periodo_id: Annotated[int | None, Query(ge=1)] = None,
    sede_id: Annotated[int | None, Query(ge=1)] = None,
    estado: Literal[
        "draft",
        "submitted",
        "under_review",
        "returned",
        "approved",
        "authorized",
        "superseded",
    ] | None = None,
    version: Annotated[int | None, Query(ge=1)] = None,
):
    """Muestra programas paginados y permite filtrar por curso y versión."""
    require_role(actor, "reader")
    responsible_id = (
        actor.id
        if "teacher" in actor.roles and not has_role(actor, "manager")
        else None
    )
    return repository.list_programs(
        session,
        page,
        per_page,
        curso_id=curso_id,
        periodo_id=periodo_id,
        sede_id=sede_id,
        estado=estado,
        version=version,
        docente_responsable_id=responsible_id,
    )


@router.post("/course-programs", status_code=201)
def post_course_program(body: ProgramaNuevo, session: DbSession, actor: CurrentActor):
    """Crea un programa con su primer borrador; requiere permiso de elaboración."""
    require_role(actor, "author")
    return repository.create_program(session, actor, body.model_dump(exclude_unset=True))


@router.get("/course-programs/{program_id}")
def course_program(program_id: int, session: DbSession, actor: CurrentActor):
    """Muestra los datos del programa y sus versiones anteriores."""
    require_role(actor, "reader")
    return repository.get_program(session, program_id)


@router.post("/course-programs/{program_id}/versions", status_code=201)
def post_version(program_id: int, body: VersionNueva, session: DbSession, actor: CurrentActor):
    """Abre otra versión copiando una autorizada; requiere gestión de programas."""
    require_role(actor, "manager")
    return repository.create_version(session, actor, program_id, body.model_dump(exclude_unset=True))


@router.get("/program-versions/{version_id}")
def read_version(version_id: int, session: DbSession, actor: CurrentActor):
    """Muestra los datos de una versión y todo su contenido."""
    require_role(actor, "reader")
    return repository.get_version(session, version_id)


@router.put("/program-versions/{version_id}")
def put_version(version_id: int, body: EncabezadoVersion, session: DbSession, actor: CurrentActor):
    """Guarda cambios de encabezado de una versión que el actor puede editar."""
    require_role(actor, "reader")
    return {"ok": True, "version": repository.update_version(
        session, actor, version_id, body.model_dump(exclude_unset=True)
    )}


@router.put("/program-versions/{version_id}/sections/evaluacion")
def put_evaluation_section(
    version_id: int,
    body: EvaluacionSeccion,
    session: DbSession,
    actor: CurrentActor,
):
    """Guarda la evaluación; acepta el formato de formulario y listas de actividades."""
    require_role(actor, "reader")
    return {"ok": True, "version": repository.update_version(
        session,
        actor,
        version_id,
        body.model_dump(exclude_unset=True),
        "evaluacion",
    )}


@router.put("/program-versions/{version_id}/sections/responsables")
def put_responsables_section(
    version_id: int,
    body: ResponsablesSeccion,
    session: DbSession,
    actor: CurrentActor,
):
    """Actualiza responsables y valida la asignación del docente en G1."""
    require_role(actor, "reader")
    return {"ok": True, "version": repository.update_version(
        session,
        actor,
        version_id,
        body.model_dump(exclude_unset=True),
        "responsables",
    )}


@router.put("/program-versions/{version_id}/sections/{section}")
def put_section(
    version_id: int,
    section: str,
    body: SeccionActualizacion,
    session: DbSession,
    actor: CurrentActor,
):
    """Guarda una sección sin tocar las demás."""
    require_role(actor, "reader")
    return {"ok": True, "version": repository.update_version(
        session, actor, version_id, body.model_dump(exclude_unset=True), section
    )}


# Acciones para enviar, revisar, devolver, aprobar y autorizar una versión.
def _transition(action: str):
    """Prepara una ruta para la acción indicada y su rol correspondiente."""
    def endpoint(
        version_id: int,
        session: DbSession,
        actor: CurrentActor,
        body: TransicionVersion | None = None,
    ):
        """Realiza la acción y devuelve la versión con su estado actualizado."""
        require_role(actor, ACTOR_ROLES[action])
        payload = body.model_dump(exclude_unset=True) if body else {}
        comment = payload.get("comentario", payload.get("observacion"))
        version = repository.transition(session, actor, version_id, action, comment)
        return {"ok": True, "version": version}

    endpoint.__name__ = f"post_{action}"
    return endpoint


router.add_api_route("/program-versions/{version_id}/submit", _transition("submit"), methods=["POST"])
router.add_api_route("/program-versions/{version_id}/review", _transition("review"), methods=["POST"])
router.add_api_route("/program-versions/{version_id}/return", _transition("return"), methods=["POST"])
router.add_api_route("/program-versions/{version_id}/approve", _transition("approve"), methods=["POST"])
router.add_api_route("/program-versions/{version_id}/authorize", _transition("authorize"), methods=["POST"])


# Rutas para consultar diferencias y bajar el PDF.
@router.get("/program-versions/{version_id}/changes")
def version_changes(version_id: int, session: DbSession, actor: CurrentActor):
    """Muestra las diferencias con la versión anterior del mismo período."""
    require_role(actor, "reader")
    return repository.get_changes(session, version_id)


@router.get("/program-versions/{version_id}/pdf")
def version_pdf(version_id: int, session: DbSession, actor: CurrentActor):
    """Genera y descarga el PDF de una versión autorizada."""
    require_role(actor, "reader")
    content, digest, program, version = repository.generate_pdf_data(session, version_id, actor)
    repository.record_pdf(session, actor, version_id, content, digest)
    filename = f"programa-{program['id']}-version-{version['numero_version']}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
