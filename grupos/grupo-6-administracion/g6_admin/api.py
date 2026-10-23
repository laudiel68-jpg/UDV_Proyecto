"""Rutas HTTP del G6. El main.py de la raíz monta `router` (README §4).

Todo lo de seguridad viene del G2 y se importa desde g2_api, no se copia:
- quién es el usuario: middleware de autenticación del G2;
- quién puede agregar o modificar: requerir_rol del G2 con el rol de administración;
- formato de error y paginación: servicios compartidos del G2.
"""

import os
import time
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Response
from g2_api.database import get_db
from g2_api.middleware.auth_middleware import obtener_usuario_actual, requerir_rol
from g2_api.utils.paginacion import Paginacion, params_paginacion
from pydantic import BaseModel, ConfigDict, Field, create_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import __version__, tablas
from .auditoria import RepositorioAuditoria, ServicioAuditoria
from .catalogos import CATALOGOS, Catalogo, RepositorioCatalogos, ServicioCatalogos
from .notificaciones import RepositorioNotificaciones, ServicioNotificaciones
from .salud import estado_del_servicio

# Código del rol en la tabla `rol` del G1 (semilla: admin, teacher, ...).
ROLES_ADMINISTRACION = ["admin"]

_INICIADO_EN = time.monotonic()

Sesion = Annotated[Session, Depends(get_db)]


def auditoria_para(sesion: Session) -> ServicioAuditoria:
    """Para el G3 y el G5: auditoria_para(db).registrar_transicion(...) y luego db.commit()."""
    return ServicioAuditoria(RepositorioAuditoria(sesion))


def notificaciones_para(sesion: Session) -> ServicioNotificaciones:
    return ServicioNotificaciones(RepositorioNotificaciones(sesion))


# La sesión es la misma de la petición (get_db del G2): el registro y su
# auditoría se guardan en una sola transacción.
def obtener_servicio(db: Sesion) -> ServicioCatalogos:
    return ServicioCatalogos(RepositorioCatalogos(db), auditoria_para(db))


def obtener_auditoria(db: Sesion) -> ServicioAuditoria:
    return auditoria_para(db)


def obtener_notificaciones(db: Sesion) -> ServicioNotificaciones:
    return notificaciones_para(db)


def _id_del_usuario(usuario: Any) -> int | None:
    # El G2 entrega el registro Usuario de la base; un diccionario también sirve.
    if isinstance(usuario, dict):
        return usuario.get("id")
    return getattr(usuario, "id", None)


Servicio = Annotated[ServicioCatalogos, Depends(obtener_servicio)]
Auditoria = Annotated[ServicioAuditoria, Depends(obtener_auditoria)]
Notificaciones = Annotated[ServicioNotificaciones, Depends(obtener_notificaciones)]
UsuarioConSesion = Annotated[Any, Depends(obtener_usuario_actual)]
Administracion = Annotated[Any, Depends(requerir_rol(ROLES_ADMINISTRACION))]

# ── Esquemas para el OpenAPI ────────────────────────────────────────────────


# Tipo con que se documenta cada campo. Las fechas entran como texto y las
# reglas completas se validan en catalogos.validar_registro.
_TIPOS_ENTRADA = {"codigo": str, "texto": str, "entero": int, "fecha": str, "booleano": bool}
_TIPOS_SALIDA = {"codigo": str, "texto": str, "entero": int, "fecha": date, "booleano": bool}


def _modelos(catalogo: Catalogo) -> tuple[type[BaseModel], type[BaseModel], type[BaseModel]]:
    """Esquemas de OpenAPI de un catálogo: alta, cambio y respuesta."""
    sufijo = "".join(p.capitalize() for p in catalogo.recurso.split("-"))
    entrada = {
        c.api: (_TIPOS_ENTRADA[c.tipo] | None, Field(
            None, examples=[c.ejemplo],
            description=("Obligatorio." if c.obligatorio else "Opcional.")
            + (f" Id de {c.referencia.name}." if c.referencia is not None else "")))
        for c in catalogo.campos}
    nuevo = create_model(f"Nuevo{sufijo}", __config__=ConfigDict(extra="forbid"), **entrada)
    cambio = create_model(f"Cambio{sufijo}", __config__=ConfigDict(extra="forbid"), **entrada)
    salida_campos: dict[str, Any] = {"id": (int, ...)}
    for c in catalogo.campos:
        tipo = _TIPOS_SALIDA[c.tipo]
        salida_campos[c.api] = (tipo if c.obligatorio or c.tipo == "booleano" else tipo | None, ...)
    salida_campos.setdefault("name", (str, ...))
    salida_campos["created_at"] = (str | None, ...)
    salida = create_model(f"{sufijo}Salida", **salida_campos)
    return nuevo, cambio, salida


class FacultadSalida(BaseModel):
    id: int
    code: str
    name: str
    is_active: bool


class NotificacionSalida(BaseModel):
    id: int
    event: str
    title: str
    message: str
    is_read: bool
    created_at: str
    read_at: str | None


class PaginaNotificaciones(BaseModel):
    page: int
    per_page: int
    total: int
    data: list[NotificacionSalida]


class RegistroAuditoriaSalida(BaseModel):
    id: int
    actor_id: int | None
    action: str
    entity: str
    entity_id: int | str
    created_at: str
    from_state: str | None
    to_state: str | None
    comment: str | None
    changes: dict[str, Any]


class PaginaAuditoria(BaseModel):
    page: int
    per_page: int
    total: int
    data: list[RegistroAuditoriaSalida]


class ResumenEventos(BaseModel):
    processed: int
    notifications: int
    failed: int


class EstadoSalud(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    time: str
    uptime_seconds: int
    checks: dict[str, str]


_ERRORES = {401: "Sin sesión", 403: "Sin permiso", 404: "No existe",
            409: "El código ya existe",
            422: "Error de validación con detalle por campo"}


def _errores(*codigos: int) -> dict[int | str, dict[str, Any]]:
    return {c: {"description": _ERRORES[c]} for c in codigos}


# ── Rutas ───────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1")


@router.get("/health", tags=["Salud"], summary="Estado técnico del servicio",
            response_model=EstadoSalud,
            responses={503: {"model": EstadoSalud,
                             "description": "Alguna verificación falló"}})
def health(response: Response) -> dict[str, Any]:
    estado = estado_del_servicio(
        iniciado_en=_INICIADO_EN,
        entorno=os.getenv("APP_ENV", "desarrollo"),
        version=os.getenv("APP_VERSION", __version__),
    )
    response.headers["Cache-Control"] = "no-store"
    if estado["status"] != "ok":
        response.status_code = 503
    return estado


def _pagina(elementos: list[dict[str, Any]], paginacion: Paginacion) -> dict[str, Any]:
    # Los catálogos son pocos registros: se filtran y paginan en Python.
    inicio = (paginacion.page - 1) * paginacion.per_page
    return {"page": paginacion.page, "per_page": paginacion.per_page,
            "total": len(elementos),
            "data": elementos[inicio:inicio + paginacion.per_page]}


def _registrar_catalogo(catalogo: Catalogo) -> None:
    ruta = f"/{catalogo.recurso}"
    sufijo = catalogo.recurso.replace("-", "_")
    Nuevo, Cambio, Salida = _modelos(catalogo)
    Pagina = create_model(f"Pagina{Salida.__name__}", page=(int, ...), per_page=(int, ...),
                          total=(int, ...), data=(list[Salida], ...))

    @router.get(ruta, tags=["Catálogos"], response_model=Pagina,
                summary=f"Listar {catalogo.nombre}",
                operation_id=f"listar_{sufijo}", responses=_errores(401, 422))
    def listar(
        servicio: Servicio,
        _usuario: UsuarioConSesion,
        paginacion: Annotated[Paginacion, Depends(params_paginacion)],
        q: Annotated[str | None, Query(
            max_length=120, description="Busca en código y nombre")] = None,
        active: Annotated[bool | None, Query(
            description="Filtra por activos (true) o inactivos (false)")] = None,
    ) -> dict[str, Any]:
        return _pagina(servicio.listar(catalogo.recurso, q=q, activo=active), paginacion)

    @router.post(ruta, tags=["Catálogos"], response_model=Salida,
                 status_code=201,
                 summary=f"Agregar a {catalogo.nombre} (solo administración)",
                 operation_id=f"crear_{sufijo}",
                 responses=_errores(401, 403, 409, 422))
    def crear(datos: Nuevo, servicio: Servicio,  # type: ignore[valid-type]
              usuario: Administracion) -> dict[str, Any]:
        return servicio.crear(catalogo.recurso,
                              datos.model_dump(exclude_unset=True),
                              _id_del_usuario(usuario))

    @router.patch(f"{ruta}/{{registro_id}}", tags=["Catálogos"],
                  response_model=Salida,
                  summary=f"Modificar en {catalogo.nombre} (solo administración)",
                  operation_id=f"modificar_{sufijo}",
                  responses=_errores(401, 403, 404, 409, 422))
    def modificar(registro_id: Annotated[int, Path(ge=1)],
                  datos: Cambio,  # type: ignore[valid-type]
                  servicio: Servicio, usuario: Administracion) -> dict[str, Any]:
        return servicio.modificar(catalogo.recurso, registro_id,
                                  datos.model_dump(exclude_unset=True),
                                  _id_del_usuario(usuario))


for _catalogo in CATALOGOS.values():
    _registrar_catalogo(_catalogo)


@router.get("/faculties", tags=["Catálogos"], response_model=list[FacultadSalida],
            summary="Facultades (para elegir al crear una unidad académica)",
            responses=_errores(401))
def listar_facultades(db: Sesion, _usuario: UsuarioConSesion) -> list[dict[str, Any]]:
    # La tabla facultad la llena el G1 en su semilla; aquí solo se lee.
    f = tablas.facultad
    return [{"id": r.id, "code": r.codigo, "name": r.nombre, "is_active": bool(r.activo)}
            for r in db.execute(select(f).order_by(f.c.nombre))]


# ── Notificaciones (G6-04 a G6-13) ──────────────────────────────────────────


@router.get("/notifications", tags=["Notificaciones"],
            response_model=PaginaNotificaciones,
            summary="Listar mis notificaciones (las más recientes primero)",
            responses=_errores(401, 422))
def listar_notificaciones(
    servicio: Notificaciones,
    usuario: UsuarioConSesion,
    paginacion: Annotated[Paginacion, Depends(params_paginacion)],
    unread: Annotated[bool, Query(
        description="true muestra solo las que no se han leído")] = False,
) -> dict[str, Any]:
    # Antes de listar se convierten en avisos los eventos nuevos que dejaron
    # G3, G4 y G5 en la tabla evento (G6-17).
    servicio.procesar_pendientes()
    total, datos = servicio.listar(_id_del_usuario(usuario), no_leidas=unread,
                                   pagina=paginacion.page, por_pagina=paginacion.per_page)
    return {"page": paginacion.page, "per_page": paginacion.per_page,
            "total": total, "data": datos}


@router.post("/notifications/process", tags=["Notificaciones"],
             response_model=ResumenEventos,
             summary="Procesar ya los eventos pendientes (solo administración)",
             responses=_errores(401, 403))
def procesar_eventos(servicio: Notificaciones, _usuario: Administracion) -> dict[str, int]:
    return servicio.procesar_pendientes()


@router.patch("/notifications/{notificacion_id}/read", tags=["Notificaciones"],
              response_model=NotificacionSalida,
              summary="Marcar como leída una notificación propia",
              responses=_errores(401, 404, 422))
def marcar_notificacion_leida(
    notificacion_id: Annotated[int, Path(ge=1)],
    servicio: Notificaciones,
    usuario: UsuarioConSesion,
) -> dict[str, Any]:
    return servicio.marcar_leida(_id_del_usuario(usuario), notificacion_id)


# ── Auditoría (G6-14, G6-15 y G6-30 a G6-33) ────────────────────────────────


@router.get("/audit", tags=["Auditoría"], response_model=PaginaAuditoria,
            summary="Consultar la auditoría (solo administración)",
            responses=_errores(401, 403, 422))
def consultar_auditoria(
    servicio: Auditoria,
    _usuario: Administracion,
    paginacion: Annotated[Paginacion, Depends(params_paginacion)],
    user_id: Annotated[int | None, Query(ge=1, description="Quién hizo la acción")] = None,
    from_: Annotated[date | None, Query(alias="from",
                                        description="Desde este día (AAAA-MM-DD, UTC)")] = None,
    to: Annotated[date | None, Query(description="Hasta este día, incluido")] = None,
    entity: Annotated[str | None, Query(
        max_length=64, description="Tabla del G1, por ejemplo sede, curso, tarea, "
                                   "programa_version o usuario")] = None,
    action: Annotated[str | None, Query(
        max_length=20, description="Por ejemplo insert, update, soft_delete o transition")] = None,
) -> dict[str, Any]:
    total, datos = servicio.consultar(actor_id=user_id, desde=from_, hasta=to,
                                      entidad=entity, accion=action,
                                      pagina=paginacion.page, por_pagina=paginacion.per_page)
    return {"page": paginacion.page, "per_page": paginacion.per_page,
            "total": total, "data": datos}
