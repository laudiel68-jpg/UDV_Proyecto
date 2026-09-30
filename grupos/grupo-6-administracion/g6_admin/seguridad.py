"""Usuarios y permisos que usa el G6.

La autenticación real (login, sesión, roles) es del G2 y el G6 la usa, no la
reimplementa (CONTRATO.md del G6 §4). Aquí solo está lo mínimo para decidir
permisos a partir del usuario que entregue el G2.
"""

from dataclasses import dataclass

from .errores import sin_permiso

# Nombres provisionales: los códigos oficiales de rol los define el G2.
ROL_ADMINISTRADOR = "admin"
ROL_DOCENTE = "teacher"


@dataclass(frozen=True)
class Usuario:
    id: int
    nombre: str
    roles: frozenset[str]

    def es_administrador(self) -> bool:
        return ROL_ADMINISTRADOR in self.roles


def exigir_administrador(usuario: Usuario, accion: str) -> None:
    """Regla del contrato: solo administradores modifican catálogos protegidos.

    Se valida en el servidor, no solo ocultando botones en la pantalla
    (escenarios G6-02 y G6-03).
    """
    if not usuario.es_administrador():
        raise sin_permiso(f"Solo administración puede {accion}.")


# TEMPORAL: usuarios ficticios para la aplicación de demostración mientras el
# G2 publica su autenticación. No contienen contraseñas ni datos reales.
USUARIOS_DEMO = {
    "admin": Usuario(id=1, nombre="Administración (demo)",
                     roles=frozenset({ROL_ADMINISTRADOR})),
    "teacher": Usuario(id=2, nombre="Docente (demo)",
                       roles=frozenset({ROL_DOCENTE})),
}
