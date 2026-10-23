"""Catálogos académicos (escenarios G6-01 a G6-03 y G6-21 a G6-25).

Aquí vive la lógica de los catálogos: cuáles existen, qué campos tiene cada
uno (los de las tablas del G1), cómo se valida un registro nuevo o un cambio y
cómo se busca, filtra y ordena una lista. Los registros se guardan en las
tablas del G1 (sede, unidad_academica, curso, periodo, modalidad y area).

Quién puede agregar o modificar registros (solo administración) lo decide
api.py con el middleware del G2. Los errores salen con el formato común del G2
(g2_api.middleware.error_handler); aquí no se reimplementa nada del G2.
"""

import json
import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from g2_api.middleware.error_handler import ErrorCode, api_error
from sqlalchemy import Table, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import tablas
from .auditoria import ServicioAuditoria

PATRON_CODIGO = re.compile(r"[A-Z0-9][A-Z0-9_-]{1,19}")  # 2 a 20 caracteres


@dataclass(frozen=True)
class Campo:
    api: str                     # Nombre en el JSON de la API
    columna: str                 # Columna en la tabla del G1
    tipo: str                    # codigo, texto, entero, fecha o booleano
    obligatorio: bool = True
    minimo: int | None = None    # Largo (texto) o valor (entero) mínimo
    maximo: int | None = None
    referencia: Table | None = None  # Tabla donde el id debe existir
    ejemplo: Any = None


@dataclass(frozen=True)
class Catalogo:
    recurso: str                 # Ruta en la API: /api/v1/<recurso>
    nombre: str                  # Nombre visible en plural, para mensajes
    tabla: Table
    campos: tuple[Campo, ...]
    borrado_logico: bool = False  # Tiene eliminado_en: lo eliminado no se lista

    @property
    def por_api(self) -> dict[str, Campo]:
        return {c.api: c for c in self.campos}


CODIGO = Campo("code", "codigo", "codigo", ejemplo="CENTRAL")
ACTIVO = Campo("is_active", "activo", "booleano", obligatorio=False, ejemplo=True)


def _nombre(maximo: int, ejemplo: str) -> Campo:
    return Campo("name", "nombre", "texto", minimo=2, maximo=maximo, ejemplo=ejemplo)


CATALOGOS: dict[str, Catalogo] = {c.recurso: c for c in (
    Catalogo("academic-units", "unidades académicas", tablas.unidad_academica, (
        CODIGO, _nombre(150, "Ingeniería en Sistemas - Sede Central"),
        Campo("faculty_id", "facultad_id", "entero", minimo=1,
              referencia=tablas.facultad, ejemplo=1),
        Campo("campus_id", "sede_id", "entero", minimo=1,
              referencia=tablas.sede, ejemplo=1),
        ACTIVO)),
    Catalogo("campuses", "sedes", tablas.sede, (
        CODIGO, _nombre(150, "Sede Central"),
        Campo("address", "direccion", "texto", obligatorio=False, maximo=300,
              ejemplo="Zona 10, Ciudad de Guatemala"),
        ACTIVO)),
    Catalogo("courses", "cursos", tablas.curso, (
        CODIGO, _nombre(150, "Programación Web"),
        Campo("credits", "creditos", "entero", minimo=1, maximo=30, ejemplo=4),
        ACTIVO), borrado_logico=True),
    Catalogo("periods", "períodos", tablas.periodo, (
        CODIGO,
        Campo("year", "anio", "entero", minimo=2000, maximo=2100, ejemplo=2027),
        Campo("cycle", "ciclo", "entero", minimo=1, maximo=4, ejemplo=1),
        Campo("start_date", "fecha_inicio", "fecha", ejemplo="2027-01-11"),
        Campo("end_date", "fecha_fin", "fecha", ejemplo="2027-06-11"),
        ACTIVO)),
    Catalogo("modalities", "modalidades", tablas.modalidad, (
        CODIGO, _nombre(100, "Presencial"), ACTIVO)),
    Catalogo("areas", "áreas", tablas.area, (
        CODIGO, _nombre(100, "Desarrollo de software"), ACTIVO)),
)}


def _ahora() -> datetime:
    # Sin zona: la columna es DATETIME y el G1 guarda todo en UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(valor: Any) -> Any:
    if isinstance(valor, datetime):
        return valor.replace(microsecond=0).isoformat() + "Z"
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def como_dict(catalogo: Catalogo, fila: Any) -> dict[str, Any]:
    """Fila de la tabla del G1 → JSON de la API (nombres en inglés del contrato)."""
    datos = fila._mapping
    salida: dict[str, Any] = {"id": datos["id"]}
    for campo in catalogo.campos:
        valor = datos[campo.columna]
        salida[campo.api] = bool(valor) if campo.tipo == "booleano" else _iso(valor)
    if "name" not in salida:
        # periodo no tiene nombre en el G1: se arma uno para mostrar.
        salida["name"] = f"Ciclo {datos['ciclo']} de {datos['anio']}"
    salida["created_at"] = _iso(datos["creado_en"])
    return salida


class RepositorioCatalogos:
    """Lee y escribe los catálogos en las tablas del G1 con una sesión de SQLAlchemy.

    La sesión es la misma que usa la auditoría, así que transaccion() guarda el
    registro y su auditoría juntos o no guarda ninguno (G6-18).
    """

    def __init__(self, sesion: Session) -> None:
        self.sesion = sesion

    @contextmanager
    def transaccion(self) -> Iterator[None]:
        try:
            yield
            self.sesion.commit()
        except BaseException:
            self.sesion.rollback()
            raise

    @staticmethod
    def _consulta(catalogo: Catalogo):
        consulta = select(catalogo.tabla)
        if catalogo.borrado_logico:
            consulta = consulta.where(catalogo.tabla.c.eliminado_en.is_(None))
        return consulta

    def listar(self, catalogo: Catalogo) -> list[Any]:
        return list(self.sesion.execute(self._consulta(catalogo)))

    def obtener(self, catalogo: Catalogo, registro_id: int) -> Any | None:
        return self.sesion.execute(self._consulta(catalogo).where(
            catalogo.tabla.c.id == registro_id)).first()

    def existe(self, tabla: Table, registro_id: int) -> bool:
        return self.sesion.execute(
            select(func.count()).select_from(tabla).where(tabla.c.id == registro_id)
        ).scalar_one() > 0

    def usa_codigo(self, catalogo: Catalogo, codigo: str, salvo_id: int | None = None) -> bool:
        consulta = select(func.count()).select_from(catalogo.tabla).where(
            catalogo.tabla.c.codigo == codigo)
        if salvo_id is not None:
            consulta = consulta.where(catalogo.tabla.c.id != salvo_id)
        return self.sesion.execute(consulta).scalar_one() > 0

    def periodo_repetido(self, anio: int, ciclo: int, salvo_id: int | None = None) -> bool:
        t = tablas.periodo
        consulta = select(func.count()).select_from(t).where(t.c.anio == anio, t.c.ciclo == ciclo)
        if salvo_id is not None:
            consulta = consulta.where(t.c.id != salvo_id)
        return self.sesion.execute(consulta).scalar_one() > 0

    def agregar(self, catalogo: Catalogo, columnas: dict[str, Any]) -> int:
        valores = dict(columnas, creado_en=_ahora())
        if "actualizado_en" in catalogo.tabla.c:
            valores["actualizado_en"] = valores["creado_en"]
        resultado = self.sesion.execute(insert(catalogo.tabla).values(**valores))
        return resultado.inserted_primary_key[0]

    def modificar(self, catalogo: Catalogo, registro_id: int, columnas: dict[str, Any]) -> None:
        valores = dict(columnas)
        if "actualizado_en" in catalogo.tabla.c:
            valores["actualizado_en"] = _ahora()
        self.sesion.execute(update(catalogo.tabla)
                            .where(catalogo.tabla.c.id == registro_id).values(**valores))


def _normalizar_busqueda(texto: str) -> str:
    """Minúsculas y sin tildes, para que "periodo" encuentre "Período"."""
    descompuesto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def _error_de_campo(campo: str, codigo: str, mensaje: str) -> dict[str, str]:
    # Misma forma que usa el G2 para el detalle de un 422.
    return {"field": campo, "code": codigo, "message": mensaje}


def _validar_campo(campo: Campo, valor: Any) -> tuple[Any, dict[str, str] | None]:
    """Devuelve el valor limpio o el error del campo."""
    nombre = campo.api
    if campo.tipo == "booleano":
        if not isinstance(valor, bool):
            return None, _error_de_campo(nombre, "BOOL_TYPE", "Debe ser verdadero o falso.")
        return valor, None

    if campo.tipo == "entero":
        if not isinstance(valor, int) or isinstance(valor, bool):
            return None, _error_de_campo(nombre, "INT_TYPE", "Debe ser un número entero.")
        if ((campo.minimo is not None and valor < campo.minimo)
                or (campo.maximo is not None and valor > campo.maximo)):
            rango = (f"entre {campo.minimo} y {campo.maximo}" if campo.maximo is not None
                     else f"desde {campo.minimo}")
            return None, _error_de_campo(nombre, "OUT_OF_RANGE", f"Usa un número {rango}.")
        return valor, None

    if campo.tipo == "fecha":
        try:
            return date.fromisoformat(valor), None
        except (TypeError, ValueError):
            return None, _error_de_campo(nombre, "DATE_FORMAT", "Usa el formato AAAA-MM-DD.")

    if not isinstance(valor, str):
        return None, _error_de_campo(nombre, "STRING_TYPE", "Debe ser texto.")
    if campo.tipo == "codigo":
        codigo = valor.strip().upper()
        if not codigo:
            return None, _error_de_campo(nombre, "REQUIRED", "El código es obligatorio.")
        if not PATRON_CODIGO.fullmatch(codigo):
            return None, _error_de_campo(
                nombre, "INVALID_FORMAT",
                "Usa de 2 a 20 caracteres: letras sin tilde, números, guion o guion bajo.")
        return codigo, None

    texto = " ".join(valor.split())
    if not texto:
        if campo.obligatorio:
            return None, _error_de_campo(nombre, "REQUIRED", "Campo obligatorio.")
        return None, None  # Un texto opcional vacío se guarda como NULL.
    if ((campo.minimo is not None and len(texto) < campo.minimo)
            or (campo.maximo is not None and len(texto) > campo.maximo)):
        return None, _error_de_campo(
            nombre, "INVALID_LENGTH",
            f"Usa entre {campo.minimo or 1} y {campo.maximo} caracteres.")
    return texto, None


def validar_registro(catalogo: Catalogo, datos: dict[str, Any], *,
                     parcial: bool = False) -> dict[str, Any]:
    """Valida y limpia un registro nuevo o un cambio. Devuelve {campo_api: valor}.

    Un registro nuevo pide todos los campos obligatorios del catálogo. Un
    cambio (parcial=True) valida solo lo que trae, y sin campos es un 422
    EMPTY_UPDATE. Los errores salen como un 422 con el error de cada campo,
    como pide el contrato común.
    """
    if parcial and not datos:
        raise api_error(422, ErrorCode.EMPTY_UPDATE,
                        "Envía al menos un campo para modificar.")
    campos = catalogo.por_api
    errores = [_error_de_campo(n, "UNKNOWN_FIELD", "Campo no reconocido.")
               for n in sorted(set(datos) - set(campos))]
    limpio: dict[str, Any] = {}
    for nombre, campo in campos.items():
        if nombre not in datos or (datos[nombre] is None and not parcial):
            if not parcial and campo.obligatorio:
                errores.append(_error_de_campo(nombre, "REQUIRED", "Campo obligatorio."))
            continue
        if datos[nombre] is None and not campo.obligatorio and campo.tipo == "texto":
            limpio[nombre] = None
            continue
        valor, error = _validar_campo(campo, datos[nombre])
        if error:
            errores.append(error)
        else:
            limpio[nombre] = valor
    if errores:
        raise api_error(422, ErrorCode.VALIDATION_ERROR,
                        "Revisa los campos marcados.", errores)
    if not parcial:
        limpio.setdefault("is_active", True)
    return limpio


class ServicioCatalogos:
    def __init__(self, repositorio: RepositorioCatalogos,
                 auditoria: ServicioAuditoria | None = None) -> None:
        self.repositorio = repositorio
        self.auditoria = auditoria

    def _auditar(self, autor_id: int | None, accion: str, catalogo: Catalogo,
                 registro_id: int, detalle: dict[str, Any]) -> None:
        # Sin id del usuario no hay a quién atribuir la acción (G6-14).
        if self.auditoria is not None and autor_id is not None:
            self.auditoria.registrar(actor_id=autor_id, accion=accion,
                                     entidad=catalogo.tabla.name, entidad_id=registro_id,
                                     cambios=detalle)

    def listar(self, recurso: str, *, q: str | None = None,
               activo: bool | None = None) -> list[dict[str, Any]]:
        """Registros filtrados y ordenados por nombre. La página la arma api.py."""
        catalogo = CATALOGOS[recurso]
        registros = [como_dict(catalogo, f) for f in self.repositorio.listar(catalogo)]

        if q and q.strip():
            buscado = _normalizar_busqueda(q.strip())
            registros = [r for r in registros
                         if buscado in _normalizar_busqueda(r["code"])
                         or buscado in _normalizar_busqueda(r["name"])]
        if activo is not None:
            registros = [r for r in registros if r["is_active"] is activo]

        registros.sort(key=lambda r: (_normalizar_busqueda(r["name"]), r["id"]))
        return registros

    def _revisar_reglas(self, catalogo: Catalogo, final: dict[str, Any],
                        cambios: dict[str, Any], salvo_id: int | None) -> None:
        """Reglas que miran la base o varios campos a la vez: 422 y luego 409."""
        errores = [
            _error_de_campo(c.api, "NOT_FOUND", "No existe un registro con ese id.")
            for c in catalogo.campos
            if c.referencia is not None and c.api in cambios
            and not self.repositorio.existe(c.referencia, cambios[c.api])
        ]
        if catalogo.recurso == "periods" and final["end_date"] <= final["start_date"]:
            errores.append(_error_de_campo(
                "end_date", "DATE_RANGE", "Debe ser posterior a la fecha de inicio."))
        if errores:
            raise api_error(422, ErrorCode.VALIDATION_ERROR,
                            "Revisa los campos marcados.", errores)

        if "code" in cambios and self.repositorio.usa_codigo(catalogo, cambios["code"], salvo_id):
            raise api_error(
                409, ErrorCode.CONFLICT,
                f"El código {cambios['code']} ya existe en {catalogo.nombre}.",
                [_error_de_campo("code", "DUPLICATE", "Este código ya está en uso.")])
        if (catalogo.recurso == "periods" and {"year", "cycle"} & set(cambios)
                and self.repositorio.periodo_repetido(final["year"], final["cycle"], salvo_id)):
            raise api_error(
                409, ErrorCode.CONFLICT,
                f"Ya existe el ciclo {final['cycle']} de {final['year']}.",
                [_error_de_campo("cycle", "DUPLICATE", "Ese año y ciclo ya existen.")])

    @staticmethod
    def _a_columnas(catalogo: Catalogo, valores: dict[str, Any]) -> dict[str, Any]:
        return {catalogo.por_api[k].columna: v for k, v in valores.items()}

    @staticmethod
    def _para_auditoria(valores: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(valores, default=str))

    def crear(self, recurso: str, datos: dict[str, Any],
              autor_id: int | None) -> dict[str, Any]:
        """Agrega un registro. El permiso ya lo revisó el middleware del G2."""
        catalogo = CATALOGOS[recurso]
        limpio = validar_registro(catalogo, datos)
        # El registro y su auditoría se guardan juntos o no se guarda ninguno (G6-18).
        with self.repositorio.transaccion():
            self._revisar_reglas(catalogo, limpio, limpio, None)
            try:
                registro_id = self.repositorio.agregar(
                    catalogo, self._a_columnas(catalogo, limpio))
            except IntegrityError:
                # Otro administrador guardó el mismo código en el mismo instante.
                raise api_error(409, ErrorCode.CONFLICT,
                                f"El registro ya existe en {catalogo.nombre}.") from None
            self._auditar(autor_id, "insert", catalogo, registro_id,
                          {"despues": self._para_auditoria(limpio)})
            return como_dict(catalogo, self.repositorio.obtener(catalogo, registro_id))

    def modificar(self, recurso: str, registro_id: int, datos: dict[str, Any],
                  autor_id: int | None = None) -> dict[str, Any]:
        """Cambia los campos enviados. El permiso ya lo revisó el middleware del G2."""
        catalogo = CATALOGOS[recurso]
        cambios = validar_registro(catalogo, datos, parcial=True)
        # El cambio y su auditoría se guardan juntos o no se guarda ninguno (G6-18).
        with self.repositorio.transaccion():
            fila = self.repositorio.obtener(catalogo, registro_id)
            if fila is None:
                raise api_error(
                    404, ErrorCode.NOT_FOUND,
                    f"No existe el registro {registro_id} en {catalogo.nombre}.")
            antes = {c.api: fila._mapping[c.columna] for c in catalogo.campos}
            final = {**antes, **cambios}
            self._revisar_reglas(catalogo, final, cambios, registro_id)
            try:
                self.repositorio.modificar(catalogo, registro_id,
                                           self._a_columnas(catalogo, cambios))
            except IntegrityError:
                raise api_error(409, ErrorCode.CONFLICT,
                                f"El registro ya existe en {catalogo.nombre}.") from None
            self._auditar(autor_id, "update", catalogo, registro_id, {
                "antes": self._para_auditoria({k: antes[k] for k in cambios}),
                "despues": self._para_auditoria(cambios)})
            return como_dict(catalogo, self.repositorio.obtener(catalogo, registro_id))

