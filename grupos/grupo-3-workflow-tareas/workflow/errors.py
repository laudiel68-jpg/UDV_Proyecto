"""Errores de dominio. Cada uno lleva el código HTTP que debe responder la API.

Los códigos de error van en MAYÚSCULAS (CONTRATO_COMUN): INVALID_TRANSITION, NOT_FOUND...
"""


class WorkflowError(Exception):
    status_code = 400
    code = "ERROR"

    def __init__(self, message, details=None, code=None):
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code.upper()      # aunque alguien pase un código en minúsculas

    def to_dict(self):
        # Formato del CONTRATO_COMUN: {"error": {"code", "message", "details"}}
        return {"error": {"code": self.code, "message": self.message,
                          "details": self.details}}


class Unauthorized(WorkflowError):
    status_code = 401
    code = "UNAUTHORIZED"


class Forbidden(WorkflowError):
    status_code = 403
    code = "FORBIDDEN"


class NotFound(WorkflowError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(WorkflowError):
    status_code = 409
    code = "CONFLICT"


class ValidationFailed(WorkflowError):
    status_code = 422
    code = "VALIDATION_ERROR"