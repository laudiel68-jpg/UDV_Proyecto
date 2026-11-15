"""Formato de errores del CONTRATO_COMUN: {"error": {"code", "message", "details"}}.

Cubre 401, 403, 404, 409 y 422. El router de G3 ya lo aplica solo (ver FormatoErrorRoute en
api.py); `register_error_handlers` sirve para una app suelta o para respuestas que no pasan
por el router (ruta inexistente, método no permitido). Si el main.py de la raíz ya registra
el manejador de G2, no hace falta llamarlo.

Los códigos van en MAYÚSCULAS (CONTRATO_COMUN).
"""
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .errors import WorkflowError

HTTP_CODES = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND",
              405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 422: "VALIDATION_ERROR"}


def validation_body(exc: RequestValidationError) -> dict:
    """422 con el detalle por campo: {"field": "priority", "message": "..."}."""
    details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
               for e in exc.errors()]
    return {"error": {"code": "VALIDATION_ERROR", "message": "Solicitud inválida",
                      "details": details}}


def register_error_handlers(app) -> None:
    @app.exception_handler(WorkflowError)
    async def _workflow_error(_, exc: WorkflowError):
        return JSONResponse(exc.to_dict(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_, exc: RequestValidationError):
        return JSONResponse(validation_body(exc), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Error"
        details = None if isinstance(exc.detail, str) else exc.detail
        return JSONResponse(
            {"error": {"code": HTTP_CODES.get(exc.status_code, "ERROR"),
                       "message": message, "details": details}},
            status_code=exc.status_code, headers=getattr(exc, "headers", None))