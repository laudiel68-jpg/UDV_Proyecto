"""Catálogos académicos (escenarios G6-01 a G6-03 y G6-21 a G6-25).

Aquí vive la lógica de los catálogos: cuáles existen, cómo se valida un
registro nuevo o un cambio y cómo se busca, filtra y ordena una lista.

Quién puede agregar o modificar registros (solo administración) lo decide api.py con el
middleware del G2. Los errores salen con el formato común del G2
(g2_api.middleware.error_handler); aquí no se reimplementa nada del G2.
"""

import copy
import re
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from g2_api.middleware.error_handler import ErrorCode, api_error

from .auditoria import ServicioAuditoria


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

# PENDIENTE: los campos reales de cada tabla son los del esquema del G1
# (sede, unidad_academica, curso, periodo, modalidad, area). Por ahora los seis
# catálogos comparten código, nombre y estado.
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


class RegistroNoEncontrado(Exception):
    pass


class RepositorioEnMemoria:
    """Guarda los registros en memoria mientras se conectan las tablas del G1.

    Los datos se pierden al reiniciar el servidor. Para pasar a MySQL se crea
    un repositorio con los mismos métodos (listar, agregar, modificar y
    transaccion) que use las tablas del G1, y el resto del código no cambia.
    """

    def __init__(self) -> None:
        self._registros: dict[str, list[Registro]] = {r: [] for r in CATALOGOS}
        self._siguiente_id = 1
        # Reentrante: transaccion() lo toma y adentro se llama a agregar o modificar.
        self._candado = threading.RLock()

    @contextmanager
    def transaccion(self) -> Iterator[None]:
        """Todo lo que se haga adentro queda completo o no queda nada (G6-18).

        Si algo falla (por ejemplo, no se pudo registrar la auditoría), los
        registros vuelven a como estaban antes. En MySQL es un
        BEGIN/COMMIT/ROLLBACK de la sesión de SQLAlchemy.
        """
        with self._candado:
            respaldo = copy.deepcopy(self._registros), self._siguiente_id
            try:
                yield
            except BaseException:
                self._registros, self._siguiente_id = respaldo
                raise

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

    def modificar(self, recurso: str, registro_id: int,
                  cambios: dict[str, Any]) -> Registro:
        with self._candado:
            registro = next((r for r in self._registros[recurso]
                             if r.id == registro_id), None)
            if registro is None:
                raise RegistroNoEncontrado(registro_id)
            code = cambios.get("code")
            if code is not None and any(r.code == code and r.id != registro_id
                                        for r in self._registros[recurso]):
                raise CodigoDuplicado(code)
            for campo, valor in cambios.items():
                setattr(registro, campo, valor)
            return registro


def _normalizar_busqueda(texto: str) -> str:
    """Minúsculas y sin tildes, para que "periodo" encuentre "Período"."""
    descompuesto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def _error_de_campo(campo: str, codigo: str, mensaje: str) -> dict[str, str]:
    # Misma forma que usa el G2 para el detalle de un 422.
    return {"field": campo, "code": codigo, "message": mensaje}


def validar_registro(datos: dict[str, Any], *, parcial: bool = False) -> dict[str, Any]:
    """Valida y limpia los datos de un registro nuevo o de un cambio.

    Un registro nuevo devuelve {"code", "name", "is_active"}. Un cambio
    (parcial=True) devuelve solo los campos enviados, y sin campos es un 422
    EMPTY_UPDATE. Los errores salen como un 422 con el error de cada campo,
    como pide el contrato común.
    """
    if parcial and not datos:
        raise api_error(422, ErrorCode.EMPTY_UPDATE,
                        "Envía al menos un campo para modificar.")
    errores: list[dict[str, str]] = []
    for campo in sorted(set(datos) - CAMPOS_PERMITIDOS):
        errores.append(_error_de_campo(campo, "UNKNOWN_FIELD", "Campo no reconocido."))

    code = datos.get("code")
    if parcial and "code" not in datos:
        pass  # Un cambio solo valida los campos que trae.
    elif code is None or (isinstance(code, str) and not code.strip()):
        errores.append(_error_de_campo("code", "REQUIRED", "El código es obligatorio."))
    elif not isinstance(code, str):
        errores.append(_error_de_campo("code", "STRING_TYPE", "El código debe ser texto."))
    else:
        code = code.strip().upper()
        if not PATRON_CODIGO.fullmatch(code):
            errores.append(_error_de_campo(
                "code", "INVALID_FORMAT",
                "Usa de 2 a 20 caracteres: letras sin tilde, números, guion o guion bajo."))

    name = datos.get("name")
    if parcial and "name" not in datos:
        pass  # Un cambio solo valida los campos que trae.
    elif name is None or (isinstance(name, str) and not name.strip()):
        errores.append(_error_de_campo("name", "REQUIRED", "El nombre es obligatorio."))
    elif not isinstance(name, str):
        errores.append(_error_de_campo("name", "STRING_TYPE", "El nombre debe ser texto."))
    else:
        name = " ".join(name.split())
        if not NOMBRE_MINIMO <= len(name) <= NOMBRE_MAXIMO:
            errores.append(_error_de_campo(
                "name", "INVALID_LENGTH",
                f"Usa entre {NOMBRE_MINIMO} y {NOMBRE_MAXIMO} caracteres."))

    is_active = datos.get("is_active")
    if is_active is None and parcial and "is_active" in datos:
        errores.append(_error_de_campo("is_active", "BOOL_TYPE",
                                       "Debe ser verdadero o falso."))
    elif is_active is None:
        is_active = True
    elif not isinstance(is_active, bool):
        errores.append(_error_de_campo("is_active", "BOOL_TYPE",
                                       "Debe ser verdadero o falso."))

    if errores:
        raise api_error(422, ErrorCode.VALIDATION_ERROR,
                        "Revisa los campos marcados.", errores)
    limpio = {"code": code, "name": name, "is_active": is_active}
    if parcial:
        return {campo: limpio[campo] for campo in datos}
    return limpio


class ServicioCatalogos:
    def __init__(self, repositorio: RepositorioEnMemoria,
                 auditoria: ServicioAuditoria | None = None) -> None:
        self.repositorio = repositorio
        self.auditoria = auditoria

    def _auditar(self, autor_id: int | None, accion: str, recurso: str,
                 registro_id: int, cambios: dict[str, Any]) -> None:
        # Sin id del usuario no hay a quién atribuir la acción (G6-14).
        if self.auditoria is not None and autor_id is not None:
            self.auditoria.registrar(actor_id=autor_id, accion=accion,
                                     entidad=recurso, entidad_id=registro_id,
                                     cambios=cambios)

    def listar(self, recurso: str, *, q: str | None = None,
               activo: bool | None = None) -> list[dict[str, Any]]:
        """Registros filtrados y ordenados por nombre. La página la arma api.py."""
        registros = self.repositorio.listar(recurso)

        if q and q.strip():
            buscado = _normalizar_busqueda(q.strip())
            registros = [r for r in registros
                         if buscado in _normalizar_busqueda(r.code)
                         or buscado in _normalizar_busqueda(r.name)]
        if activo is not None:
            registros = [r for r in registros if r.is_active is activo]

        registros.sort(key=lambda r: (_normalizar_busqueda(r.name), r.id))
        return [r.como_dict() for r in registros]

    def crear(self, recurso: str, datos: dict[str, Any],
              autor_id: int | None) -> dict[str, Any]:
        """Agrega un registro. El permiso ya lo revisó el middleware del G2."""
        catalogo = CATALOGOS[recurso]
        limpio = validar_registro(datos)
        # El registro y su auditoría se guardan juntos o no se guarda ninguno (G6-18).
        with self.repositorio.transaccion():
            try:
                registro = self.repositorio.agregar(recurso, autor_id=autor_id, **limpio)
            except CodigoDuplicado:
                raise api_error(
                    409, ErrorCode.CONFLICT,
                    f"El código {limpio['code']} ya existe en {catalogo.nombre}.",
                    [_error_de_campo("code", "DUPLICATE", "Este código ya está en uso.")],
                ) from None
            self._auditar(autor_id, "create", recurso, registro.id, limpio)
            return registro.como_dict()

    def modificar(self, recurso: str, registro_id: int, datos: dict[str, Any],
                  autor_id: int | None = None) -> dict[str, Any]:
        """Cambia los campos enviados. El permiso ya lo revisó el middleware del G2."""
        catalogo = CATALOGOS[recurso]
        cambios = validar_registro(datos, parcial=True)
        # El cambio y su auditoría se guardan juntos o no se guarda ninguno (G6-18).
        with self.repositorio.transaccion():
            try:
                registro = self.repositorio.modificar(recurso, registro_id, cambios)
            except RegistroNoEncontrado:
                raise api_error(
                    404, ErrorCode.NOT_FOUND,
                    f"No existe el registro {registro_id} en {catalogo.nombre}.",
                ) from None
            except CodigoDuplicado:
                raise api_error(
                    409, ErrorCode.CONFLICT,
                    f"El código {cambios['code']} ya existe en {catalogo.nombre}.",
                    [_error_de_campo("code", "DUPLICATE", "Este código ya está en uso.")],
                ) from None
            self._auditar(autor_id, "update", recurso, registro.id, cambios)
            return registro.como_dict()
