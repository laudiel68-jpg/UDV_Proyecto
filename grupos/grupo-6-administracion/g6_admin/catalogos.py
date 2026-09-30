"""Catálogos académicos (escenarios G6-01 a G6-03 y G6-21 a G6-25).

Aquí vive toda la lógica: qué catálogos existen, cómo se valida un registro,
quién puede crearlo y cómo se lista con búsqueda y paginación.

Este archivo NO importa FastAPI a propósito. El framework todavía está
pendiente (README §5); si el PM elige otro, esta lógica se conserva tal cual y
solo cambia api.py.
"""

import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .errores import conflicto, no_encontrado, validacion
from .paginacion import PER_PAGE_PREDETERMINADO, paginar
from .seguridad import Usuario, exigir_administrador


@dataclass(frozen=True)
class Catalogo:
    recurso: str  # Ruta en la API: /api/v1/<recurso>
    nombre: str   # Nombre visible en plural, para mensajes


CATALOGOS: dict[str, Catalogo] = {c.recurso: c for c in (
    Catalogo("academic-units", "unidades académicas"),
    Catalogo("campuses", "sedes"),
    Catalogo("courses", "cursos"),
    Catalogo("periods", "períodos"),
    Catalogo("modalities", "modalidades"),
    Catalogo("areas", "áreas"),
)}

# PENDIENTE: los campos reales de cada tabla los define el diccionario de datos
# del G1 (por ejemplo, fechas del período o créditos del curso). Por ahora los
# seis catálogos comparten código, nombre y estado.
CAMPOS_PERMITIDOS = frozenset({"code", "name", "is_active"})
PATRON_CODIGO = re.compile(r"[A-Z0-9][A-Z0-9_-]{1,19}")  # 2 a 20 caracteres
NOMBRE_MINIMO, NOMBRE_MAXIMO = 2, 120


@dataclass
class Registro:
    id: int
    code: str
    name: str
    is_active: bool
    created_at: str
    created_by: int | None

    def como_dict(self) -> dict[str, Any]:
        return {"id": self.id, "code": self.code, "name": self.name,
                "is_active": self.is_active, "created_at": self.created_at}


class CodigoDuplicado(Exception):
    pass


class RepositorioEnMemoria:
    """Guarda los registros en memoria mientras el G1 entrega las tablas.

    Los datos se pierden al reiniciar el servidor. Cuando exista la base, se
    crea un repositorio con los mismos métodos (listar y agregar) que use las
    tablas del G1, y el resto del código no cambia.
    """

    def __init__(self) -> None:
        self._registros: dict[str, list[Registro]] = {r: [] for r in CATALOGOS}
        self._siguiente_id = 1
        self._candado = threading.Lock()

    def listar(self, recurso: str) -> list[Registro]:
        with self._candado:
            return list(self._registros[recurso])

    def agregar(self, recurso: str, *, code: str, name: str, is_active: bool,
                autor_id: int | None) -> Registro:
        with self._candado:
            if any(r.code == code for r in self._registros[recurso]):
                raise CodigoDuplicado(code)
            registro = Registro(
                id=self._siguiente_id, code=code, name=name, is_active=is_active,
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                created_by=autor_id,
            )
            self._siguiente_id += 1
            self._registros[recurso].append(registro)
            return registro


def _normalizar_busqueda(texto: str) -> str:
    """Minúsculas y sin tildes, para que "periodo" encuentre "Período"."""
    descompuesto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def validar_registro(datos: Any) -> dict[str, Any]:
    """Valida y limpia los datos de un registro nuevo.

    Devuelve {"code", "name", "is_active"} o lanza un 422 con el error de cada
    campo, como pide el contrato común.
    """
    if not isinstance(datos, dict):
        raise validacion({"_body": "Envía un objeto JSON."})

    errores: dict[str, str] = {}
    for campo in sorted(set(datos) - CAMPOS_PERMITIDOS):
        errores[campo] = "Campo no reconocido."

    code = datos.get("code")
    if code is None or (isinstance(code, str) and not code.strip()):
        errores["code"] = "El código es obligatorio."
    elif not isinstance(code, str):
        errores["code"] = "El código debe ser texto."
    else:
        code = code.strip().upper()
        if not PATRON_CODIGO.fullmatch(code):
            errores["code"] = ("Usa de 2 a 20 caracteres: letras sin tilde, "
                               "números, guion o guion bajo.")

    name = datos.get("name")
    if name is None or (isinstance(name, str) and not name.strip()):
        errores["name"] = "El nombre es obligatorio."
    elif not isinstance(name, str):
        errores["name"] = "El nombre debe ser texto."
    else:
        name = " ".join(name.split())
        if not NOMBRE_MINIMO <= len(name) <= NOMBRE_MAXIMO:
            errores["name"] = (f"Usa entre {NOMBRE_MINIMO} y {NOMBRE_MAXIMO} "
                               "caracteres.")

    is_active = datos.get("is_active", True)
    if not isinstance(is_active, bool):
        errores["is_active"] = "Debe ser verdadero o falso."

    if errores:
        raise validacion(errores)
    return {"code": code, "name": name, "is_active": is_active}


class ServicioCatalogos:
    def __init__(self, repositorio: RepositorioEnMemoria) -> None:
        self.repositorio = repositorio

    def obtener_catalogo(self, recurso: str) -> Catalogo:
        catalogo = CATALOGOS.get(recurso)
        if catalogo is None:
            raise no_encontrado("Ese catálogo no existe.")
        return catalogo

    def listar(self, recurso: str, *, page: int = 1,
               per_page: int = PER_PAGE_PREDETERMINADO, q: str | None = None,
               activo: bool | None = None) -> dict[str, Any]:
        self.obtener_catalogo(recurso)
        registros = self.repositorio.listar(recurso)

        if q and q.strip():
            buscado = _normalizar_busqueda(q.strip())
            registros = [r for r in registros
                         if buscado in _normalizar_busqueda(r.code)
                         or buscado in _normalizar_busqueda(r.name)]
        if activo is not None:
            registros = [r for r in registros if r.is_active is activo]

        registros.sort(key=lambda r: (_normalizar_busqueda(r.name), r.id))
        return paginar([r.como_dict() for r in registros], page, per_page)

    def crear(self, recurso: str, datos: Any, usuario: Usuario) -> dict[str, Any]:
        catalogo = self.obtener_catalogo(recurso)
        # Primero el permiso y después la validación: así alguien sin permiso
        # no puede usar los mensajes de error para explorar el catálogo.
        exigir_administrador(usuario, f"modificar el catálogo de {catalogo.nombre}")
        limpio = validar_registro(datos)
        try:
            registro = self.repositorio.agregar(recurso, autor_id=usuario.id, **limpio)
        except CodigoDuplicado:
            raise conflicto(
                f"El código {limpio['code']} ya existe en {catalogo.nombre}.",
                {"code": "Este código ya está en uso."},
            ) from None
        return registro.como_dict()
