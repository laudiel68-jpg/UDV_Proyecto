"""Aplicación de demostración para correr el módulo del G6 por separado.

El punto de entrada oficial de todo el sistema es del PM (README §4). Esta app
solo sirve para desarrollar y mostrar avances del G6 en una computadora local.

Correr:  python -m g6_admin      (desde grupos/grupo-6-administracion)
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import instalar
from .errores import solicitud_invalida, validacion

registro = logging.getLogger(__name__)

CARPETA_PANTALLAS = Path(__file__).parent / "pantallas"
CARPETA_ESTILOS_UDV = Path(__file__).resolve().parents[2] / "udv-styles"

# ── Manejadores globales de errores ────────────────────────────────────────
# TEMPORAL: en la app integrada esto lo hace el middleware del G2. Aquí solo
# existen para que la demo responda con el formato del contrato común.

MENSAJES_VALIDACION = {
    "missing": "Campo obligatorio.",
    "extra_forbidden": "Campo no reconocido.",
    "string_type": "Debe ser texto.",
    "bool_type": "Debe ser verdadero o falso.",
    "bool_parsing": "Debe ser verdadero o falso.",
    "int_type": "Debe ser un número entero.",
    "int_parsing": "Debe ser un número entero.",
    "greater_than_equal": "El valor es menor que el mínimo permitido.",
    "less_than_equal": "El valor supera el máximo permitido.",
    "string_too_long": "El texto es demasiado largo.",
    "model_attributes_type": "Envía un objeto JSON.",
}
UBICACIONES = {"body", "query", "path", "header"}


async def _error_de_validacion(_request: Request,
                               error: RequestValidationError) -> JSONResponse:
    errores = error.errors()
    if any(e.get("type") == "json_invalid" for e in errores):
        problema = solicitud_invalida("El cuerpo de la solicitud no es un JSON válido.")
        return JSONResponse(status_code=400, content=problema.como_json())

    detalles: dict[str, str] = {}
    for e in errores:
        partes = [str(p) for p in e.get("loc", ()) if p not in UBICACIONES]
        campo = ".".join(partes) or "_body"
        detalles.setdefault(campo, MENSAJES_VALIDACION.get(e.get("type"),
                                                           "Valor inválido."))
    return JSONResponse(status_code=422, content=validacion(detalles).como_json())


async def _error_http(_request: Request,
                      error: StarletteHTTPException) -> JSONResponse:
    conocidos = {404: ("NOT_FOUND", "La ruta solicitada no existe."),
                 405: ("METHOD_NOT_ALLOWED", "Ese método no está permitido en esta ruta.")}
    codigo, mensaje = conocidos.get(
        error.status_code, ("HTTP_ERROR", "No se pudo completar la solicitud."))
    return JSONResponse(status_code=error.status_code,
                        content={"error": {"code": codigo, "message": mensaje,
                                           "details": {}}},
                        headers=getattr(error, "headers", None))


async def _error_inesperado(_request: Request, error: Exception) -> JSONResponse:
    # El detalle queda solo en el registro del servidor; al cliente nunca se le
    # envían trazas, SQL ni rutas internas (RNF 06, escenario G6-36).
    registro.error("Error inesperado: %s", type(error).__name__)
    return JSONResponse(status_code=500, content={"error": {
        "code": "INTERNAL_ERROR",
        "message": "Ocurrió un error inesperado. Intenta de nuevo.",
        "details": {}}})


# ── Fábrica de la app ──────────────────────────────────────────────────────


def crear_app_demo(*, auth_demo: bool = True, datos_ejemplo: bool = True) -> FastAPI:
    app = FastAPI(title="UDV Workflow Docente: módulo del Grupo 6 (demo local)",
                  version=__version__)
    instalar(app, auth_demo=auth_demo, datos_ejemplo=datos_ejemplo)

    app.add_exception_handler(RequestValidationError, _error_de_validacion)
    app.add_exception_handler(StarletteHTTPException, _error_http)
    app.add_exception_handler(Exception, _error_inesperado)

    app.mount("/g6", StaticFiles(directory=CARPETA_PANTALLAS, html=True),
              name="pantallas_g6")
    if CARPETA_ESTILOS_UDV.is_dir():
        # Solo se sirve la carpeta del PM; no se copia ni se modifica.
        app.mount("/udv-styles", StaticFiles(directory=CARPETA_ESTILOS_UDV),
                  name="udv_styles")

    @app.get("/", include_in_schema=False)
    def inicio() -> RedirectResponse:
        return RedirectResponse("/g6/catalogos.html")

    return app


app = crear_app_demo()
