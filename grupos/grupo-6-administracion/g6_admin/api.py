"""Capa HTTP del G6 con FastAPI.

Es la ÚNICA parte que depende del framework. La lógica está en catalogos.py y
salud.py. Si el PM elige otro framework (README §5), solo se reescribe este
archivo y app_demo.py.

Uso desde la aplicación principal:  instalar(app)
"""

import os
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .catalogos import CATALOGOS, Catalogo, RepositorioEnMemoria, ServicioCatalogos
from .datos_ejemplo import cargar_datos_ejemplo
from .errores import ErrorApi, no_autenticado
from .paginacion import PER_PAGE_MAXIMO
from .salud import estado_del_servicio
from .seguridad import USUARIOS_DEMO, Usuario

# ── Esquemas para el OpenAPI ────────────────────────────────────────────────


class ErrorDetalle(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorRespuesta(BaseModel):
    error: ErrorDetalle


class RegistroNuevo(BaseModel):
    """Las reglas completas se validan en catalogos.validar_registro."""

    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(
        None, examples=["CENTRAL"],
        description="Obligatorio. De 2 a 20 caracteres: letras, números, guion "
                    "o guion bajo. Se guarda en mayúsculas.")
    name: str | None = Field(
        None, examples=["Campus Central"],
        description="Obligatorio. De 2 a 120 caracteres.")
    is_active: bool | None = Field(
        None, description="Opcional. Si se omite, el registro queda activo.")


class RegistroSalida(BaseModel):
    id: int
    code: str
    name: str
    is_active: bool
    created_at: str


class PaginaRegistros(BaseModel):
    page: int
    per_page: int
    total: int
    data: list[RegistroSalida]


class EstadoSalud(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    time: str
    uptime_seconds: int
    checks: dict[str, str]


def _errores(*codigos: int) -> dict[int | str, dict[str, Any]]:
    descripciones = {400: "Solicitud mal formada", 401: "No autenticado",
                     403: "Sin permiso", 409: "Conflicto",
                     422: "Error de validación con detalle por campo"}
    return {c: {"model": ErrorRespuesta, "description": descripciones[c]}
            for c in codigos}


# ── Dependencias ────────────────────────────────────────────────────────────


def obtener_servicio(request: Request) -> ServicioCatalogos:
    return request.app.state.g6_catalogos


def usuario_actual(
    request: Request,
    x_demo_role: Annotated[str | None, Header(
        description="TEMPORAL, solo funciona en la app de demostración: "
                    "admin o teacher. Se elimina cuando el G2 publique su "
                    "autenticación.")] = None,
) -> Usuario:
    """Punto de conexión con la autenticación del G2.

    Mientras el G2 no publique su middleware, esta función solo acepta el
    encabezado de demostración si la app se creó con auth_demo=True. En
    cualquier otra app responde 401: el encabezado nunca abre una puerta en la
    aplicación real.
    """
    if not getattr(request.app.state, "g6_auth_demo", False):
        raise no_autenticado()
    usuario = USUARIOS_DEMO.get((x_demo_role or "").strip().lower())
    if usuario is None:
        raise no_autenticado()
    return usuario


Servicio = Annotated[ServicioCatalogos, Depends(obtener_servicio)]
UsuarioActual = Annotated[Usuario, Depends(usuario_actual)]

# ── Rutas ───────────────────────────────────────────────────────────────────

router = APIRouter()


@router.get("/health", tags=["Salud"], summary="Estado técnico del servicio",
            response_model=EstadoSalud,
            responses={503: {"model": EstadoSalud,
                             "description": "Alguna verificación falló"}})
def health(request: Request, response: Response) -> dict[str, Any]:
    estado = estado_del_servicio(
        iniciado_en=request.app.state.g6_iniciado_en,
        entorno=os.getenv("APP_ENV", "desarrollo"),
        version=os.getenv("APP_VERSION", __version__),
    )
    response.headers["Cache-Control"] = "no-store"
    if estado["status"] != "ok":
        response.status_code = 503
    return estado


def _registrar_catalogo(catalogo: Catalogo) -> None:
    ruta = f"/{catalogo.recurso}"
    sufijo = catalogo.recurso.replace("-", "_")

    @router.get(ruta, tags=["Catálogos"], response_model=PaginaRegistros,
                summary=f"Listar {catalogo.nombre}",
                operation_id=f"listar_{sufijo}", responses=_errores(401, 422))
    def listar(
        servicio: Servicio,
        _usuario: UsuarioActual,
        page: Annotated[int, Query(ge=1)] = 1,
        per_page: Annotated[int, Query(ge=1, le=PER_PAGE_MAXIMO)] = 20,
        q: Annotated[str | None, Query(
            max_length=120, description="Busca en código y nombre")] = None,
        active: Annotated[bool | None, Query(
            description="Filtra por activos (true) o inactivos (false)")] = None,
    ) -> dict[str, Any]:
        return servicio.listar(catalogo.recurso, page=page, per_page=per_page,
                               q=q, activo=active)

    @router.post(ruta, tags=["Catálogos"], response_model=RegistroSalida,
                 status_code=201, summary=f"Agregar a {catalogo.nombre} "
                                          "(solo administración)",
                 operation_id=f"crear_{sufijo}",
                 responses=_errores(400, 401, 403, 409, 422))
    def crear(datos: RegistroNuevo, servicio: Servicio,
              usuario: UsuarioActual) -> dict[str, Any]:
        return servicio.crear(catalogo.recurso,
                              datos.model_dump(exclude_unset=True), usuario)


for _catalogo in CATALOGOS.values():
    _registrar_catalogo(_catalogo)

# ── Instalación en una app ──────────────────────────────────────────────────


async def _responder_error_api(_request: Request, error: ErrorApi) -> JSONResponse:
    return JSONResponse(status_code=error.estado_http, content=error.como_json())


def instalar(app: FastAPI, *, auth_demo: bool = False,
             datos_ejemplo: bool = False) -> None:
    """Conecta las rutas del G6 bajo /api/v1 en la app que se le pase."""
    servicio = ServicioCatalogos(RepositorioEnMemoria())
    if datos_ejemplo:
        cargar_datos_ejemplo(servicio)

    app.state.g6_catalogos = servicio
    app.state.g6_auth_demo = auth_demo
    app.state.g6_iniciado_en = time.monotonic()
    app.include_router(router, prefix="/api/v1")
    app.add_exception_handler(ErrorApi, _responder_error_api)
