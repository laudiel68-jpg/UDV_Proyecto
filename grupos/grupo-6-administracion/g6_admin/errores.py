"""Formato de error común (CONTRATO_COMUN.md §1).

TEMPORAL: el G2 es dueño del formato de error y del middleware. Cuando el G2
publique su versión en g2_api, este archivo se reemplaza por ese import.
"""

from typing import Any


class ErrorApi(Exception):
    """Error que la API devuelve como {"error": {"code", "message", "details"}}."""

    def __init__(self, estado_http: int, codigo: str, mensaje: str,
                 detalles: dict[str, Any] | None = None) -> None:
        super().__init__(mensaje)
        self.estado_http = estado_http
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalles = detalles or {}

    def como_json(self) -> dict[str, Any]:
        return {"error": {"code": self.codigo, "message": self.mensaje,
                          "details": self.detalles}}


def solicitud_invalida(mensaje: str) -> ErrorApi:
    return ErrorApi(400, "BAD_REQUEST", mensaje)


def no_autenticado() -> ErrorApi:
    return ErrorApi(401, "UNAUTHENTICATED", "Inicia sesión para continuar.")


def sin_permiso(mensaje: str) -> ErrorApi:
    return ErrorApi(403, "FORBIDDEN", mensaje)


def no_encontrado(mensaje: str) -> ErrorApi:
    return ErrorApi(404, "NOT_FOUND", mensaje)


def conflicto(mensaje: str, detalles: dict[str, Any] | None = None) -> ErrorApi:
    return ErrorApi(409, "CONFLICT", mensaje, detalles)


def validacion(detalles: dict[str, Any]) -> ErrorApi:
    """422 con el detalle por campo que pide el contrato común."""
    return ErrorApi(422, "VALIDATION_ERROR", "Revisa los campos marcados.", detalles)
