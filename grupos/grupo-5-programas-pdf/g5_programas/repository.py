"""Lectura y guardado de programas en las tablas que comparte G1.

Aquí se conectan los datos del formulario con la base de datos. También se
revisan las reglas del flujo, se guarda el historial y se preparan los datos
que necesita el PDF.
"""

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import Actor, has_role
from .database import set_database_actor
from .domain import editable, next_status
from .errors import ApiError

MAIN_SELECT = """
SELECT pv.*, pc.curso_id, pc.sede_id, pc.modalidad_id, pc.activo,
       c.codigo AS curso_codigo, c.nombre AS curso_nombre,
       s.codigo AS sede_codigo, s.nombre AS sede_nombre,
       m.codigo AS modalidad_codigo, m.nombre AS modalidad_nombre,
       p.codigo AS periodo_codigo
FROM programa_version pv
JOIN programa_curso pc ON pc.id = pv.programa_curso_id
JOIN curso c ON c.id = pc.curso_id
JOIN sede s ON s.id = pc.sede_id
JOIN modalidad m ON m.id = pc.modalidad_id
JOIN periodo p ON p.id = pv.periodo_id
"""


# Ayudas para leer datos de la base y dejarlos listos para la API.
def json_value(value):
    """Pasa fechas, decimales y datos anidados a formatos que entiende JSON."""
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime):
            return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


def _one(session: Session, query: str, params=None):
    """Busca una fila y la devuelve como diccionario, o None si no hay resultado."""
    row = session.execute(text(query), params or {}).mappings().first()
    return dict(row) if row else None


def _all(session: Session, query: str, params=None):
    """Busca varias filas y las devuelve como una lista de diccionarios."""
    return [dict(row) for row in session.execute(text(query), params or {}).mappings()]


def _version_row(session: Session, version_id: int, lock=False):
    """Busca una versión con los datos de su curso y período."""
    query = MAIN_SELECT + " WHERE pv.id = :id" + (" FOR UPDATE" if lock else "")
    return _one(session, query, {"id": version_id})


def _program_row(session: Session, program_id: int):
    """Trae los datos del programa y encuentra cuál es su versión vigente."""
    return _one(
        session,
        """SELECT pc.*, c.codigo AS codigo, c.nombre AS asignatura,
                  s.nombre AS sede, m.nombre AS modalidad,
                  (SELECT MAX(v.numero_version) FROM programa_version v
                   WHERE v.programa_curso_id = pc.id AND v.estado_codigo = 'authorized')
                   AS version_actual,
                  (SELECT v.periodo_id FROM programa_version v
                   WHERE v.programa_curso_id = pc.id AND v.estado_codigo = 'authorized'
                   ORDER BY v.numero_version DESC LIMIT 1) AS periodo_id
           FROM programa_curso pc
           JOIN curso c ON c.id = pc.curso_id
           JOIN sede s ON s.id = pc.sede_id
           JOIN modalidad m ON m.id = pc.modalidad_id
           WHERE pc.id = :id""",
        {"id": program_id},
    )


def _section(content):
    """Deja el contenido con el formato que espera la API para cada sección."""
    return {"contenido": content}


def _validate_evaluations(content: list) -> None:
    """Valida las actividades antes de borrar o insertar filas de evaluación."""
    for index, item in enumerate(content):
        prefix = f"evaluacion[{index}]"
        if not isinstance(item, dict):
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "Cada actividad de evaluación debe ser un objeto.",
                {prefix: "Se requiere un objeto."},
            )

        details = {}
        if not isinstance(item.get("nombre"), str) or not item["nombre"].strip():
            details[f"{prefix}.nombre"] = "Campo obligatorio."
        raw_weight = item.get("ponderacion")
        if raw_weight is None or isinstance(raw_weight, bool):
            details[f"{prefix}.ponderacion"] = "Campo obligatorio y numérico."
        else:
            try:
                weight = Decimal(str(raw_weight))
            except (InvalidOperation, ValueError):
                details[f"{prefix}.ponderacion"] = "Debe ser numérica."
            else:
                if not weight.is_finite():
                    details[f"{prefix}.ponderacion"] = "Debe ser un número finito."
        if details:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "La actividad de evaluación está incompleta o es inválida.",
                details,
            )


# Carga y guardado de las secciones del formulario.
def _load_sections(session: Session, version: dict) -> dict:
    """Arma las secciones que muestra el formulario usando los datos guardados.

    Algunos nombres de la base son distintos a los del formulario; aquí se
    adaptan y también se recupera el contenido adicional que guarda G5.
    """
    version_id = version["id"]
    description = version.get("descripcion") or ""
    methodology = ""
    if isinstance(description, str) and description.startswith("G5:"):
        try:
            encoded = json.loads(description[3:])
        except json.JSONDecodeError:
            encoded = {}
        if isinstance(encoded, dict):
            description = encoded.get("descripcion", "")
            methodology = encoded.get("metodologia", "")
    sections = {
        "general": _section({
            "codigo": version["curso_codigo"],
            "asignatura": version["nombre"],
            "programa": version.get("programa_academico"),
            "departamento": version.get("departamento"),
            "ciclo": version["periodo_codigo"],
            "periodo_id": version["periodo_id"],
            "unidad_academica_id": version.get("unidad_academica_id"),
            "area_id": version.get("area_id"),
            "nivel": version.get("nivel"),
            "horas": version.get("horas_clase_semanal"),
            "sede": version["sede_nombre"],
            "modalidad": version["modalidad_nombre"],
            "pensum": version.get("pensum"),
            "resumen_cambios": version.get("resumen_cambios"),
        }),
        "descripcion": _section({"texto": description}),
        "metodologia": _section({"texto": methodology}),
    }

    prerequisites = _all(
        session,
        """SELECT pr.curso_requerido_id AS curso_id, pr.orden, pr.tipo,
                  c.codigo, c.nombre
           FROM programa_prerrequisito pr
           JOIN curso c ON c.id = pr.curso_requerido_id
           WHERE pr.programa_version_id = :id ORDER BY pr.orden""",
        {"id": version_id},
    )
    sections["prerrequisitos"] = _section(prerequisites)
    sections["competencias"] = _section(_all(
        session,
        """SELECT orden, tipo, descripcion FROM programa_competencia
           WHERE programa_version_id = :id ORDER BY orden""",
        {"id": version_id},
    ))
    units = _all(
        session,
        """SELECT id, unidad_padre_id, orden, titulo, horas
           FROM programa_unidad WHERE programa_version_id = :id ORDER BY orden""",
        {"id": version_id},
    )
    items = _all(
        session,
        """SELECT ui.programa_unidad_id, ui.orden, ui.item, ui.descripcion,
                  ui.actividad, ui.evidencia, ui.punteo
           FROM programa_unidad_item ui
           JOIN programa_unidad pu ON pu.id = ui.programa_unidad_id
           WHERE pu.programa_version_id = :id ORDER BY pu.orden, ui.orden""",
        {"id": version_id},
    )
    items_by_unit = {}
    for item in items:
        items_by_unit.setdefault(item["programa_unidad_id"], []).append(item)
    sections["contenidos"] = _section([
        {
            "orden": unit["orden"],
            "titulo": unit["titulo"],
            "horas": unit["horas"],
            "items": items_by_unit.get(unit["id"], []),
        }
        for unit in units
    ])
    sections["bibliografia"] = _section(_all(
        session,
        """SELECT orden, tipo, referencia, isbn, url
           FROM programa_bibliografia
           WHERE programa_version_id = :id ORDER BY orden""",
        {"id": version_id},
    ))
    sections["evaluacion"] = _section(_all(
        session,
        """SELECT orden, nombre, descripcion, ponderacion, semana
           FROM programa_evaluacion
           WHERE programa_version_id = :id ORDER BY orden""",
        {"id": version_id},
    ))
    sections["perfil"] = _section(_all(
        session,
        """SELECT pe.perfil_egreso_id, pe.orden, pe.contribucion, eg.codigo, eg.descripcion
           FROM programa_perfil_egreso pe
           JOIN perfil_egreso eg ON eg.id = pe.perfil_egreso_id
           WHERE pe.programa_version_id = :id ORDER BY pe.orden""",
        {"id": version_id},
    ))
    people = _one(
        session,
        """SELECT pv.docente_responsable_id,
                  CONCAT_WS(' ', d.nombres, d.apellidos) AS docente,
                  CONCAT_WS(' ', r.nombres, r.apellidos) AS revisor,
                  CONCAT_WS(' ', a.nombres, a.apellidos) AS autoridad
           FROM programa_version pv
           LEFT JOIN usuario d ON d.id = pv.docente_responsable_id
           LEFT JOIN usuario r ON r.id = pv.revisor_id
           LEFT JOIN usuario a ON a.id = pv.autorizado_por
           WHERE pv.id = :id""",
        {"id": version_id},
    ) or {}
    sections["responsables"] = _section(people)
    return json_value(sections)


def _serialize_version(session: Session, row: dict, include_sections=True) -> dict:
    """Prepara los datos de una versión para enviarlos a la API."""
    version = {
        "id": row["id"],
        "programa_id": row["programa_curso_id"],
        "programa_curso_id": row["programa_curso_id"],
        "numero_version": row["numero_version"],
        "periodo_id": row["periodo_id"],
        "estado": row["estado_codigo"],
        "version_origen_id": row["version_origen_id"],
        "nombre": row["nombre"],
        "descripcion": row["descripcion"],
        "resumen_cambios": row["resumen_cambios"],
        "creado_en": row["creado_en"],
        "actualizado_en": row["actualizado_en"],
        "autorizado_en": row["autorizado_en"],
    }
    if include_sections:
        version["secciones"] = _load_sections(session, row)
    return json_value(version)


def _require_version(session: Session, version_id: int, lock=False):
    """Busca la versión y avisa con un 404 si no existe."""
    row = _version_row(session, version_id, lock)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Versión no encontrada.")
    return row


def _save_section(
    session: Session,
    version_id: int,
    section: str,
    content: dict | list,
    actor_id: int | None = None,
    responsible_context: dict | None = None,
):
    """Guarda los datos de una sección en las tablas correspondientes de G1.

    Antes de guardar, comprueba que los datos tengan el formato esperado.
    """
    if section in {"general", "descripcion", "metodologia", "responsables"} and not isinstance(content, dict):
        raise ApiError(422, "VALIDATION_ERROR", "El contenido de la sección debe ser un objeto.", {"contenido": "Se requiere un objeto."})
    if section in {"prerrequisitos", "competencias", "perfil", "contenidos", "bibliografia", "evaluacion"} and not isinstance(content, (dict, list)):
        raise ApiError(422, "VALIDATION_ERROR", "El contenido de la sección no es válido.", {"contenido": "Se requiere un objeto o una lista."})
    if section == "general":
        aliases = {
            "asignatura": "nombre",
            "programa": "programa_academico",
            "departamento": "departamento",
            "nivel": "nivel",
            "pensum": "pensum",
            "horas": "horas_clase_semanal",
            "resumen_cambios": "resumen_cambios",
            "unidad_academica_id": "unidad_academica_id",
            "area_id": "area_id",
            "periodo_id": "periodo_id",
        }
        fields = {column: content[key] for key, column in aliases.items() if key in content}
        if fields:
            assignments = ", ".join(f"{column} = :{column}" for column in fields)
            session.execute(
                text(f"UPDATE programa_version SET {assignments} WHERE id = :id"),
                {**fields, "id": version_id},
            )
    elif section in {"descripcion", "metodologia"}:
        row = _one(session, "SELECT descripcion FROM programa_version WHERE id = :id", {"id": version_id})
        stored = (row or {}).get("descripcion") or ""
        data = {}
        if isinstance(stored, str) and stored.startswith("G5:"):
            try:
                parsed = json.loads(stored[3:])
                if isinstance(parsed, dict):
                    data = parsed
            except json.JSONDecodeError:
                data = {}
        key = "descripcion" if section == "descripcion" else "metodologia"
        data[key] = content.get("texto", content.get(key, "")) if isinstance(content, dict) else ""
        session.execute(
            text("UPDATE programa_version SET descripcion = :descripcion WHERE id = :id"),
            {"descripcion": "G5:" + json.dumps(data, ensure_ascii=False), "id": version_id},
        )
    elif section == "responsables":
        raw_responsible_id = content.get("docente_responsable_id")
        if raw_responsible_id is None:
            return
        if responsible_context is None:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "No se pudo validar el docente responsable para este programa.",
                {"docente_responsable_id": "Falta el contexto del curso, período y sede."},
            )
        responsible_id = _validate_responsible_teacher(
            session,
            raw_responsible_id,
            responsible_context["curso_id"],
            responsible_context["periodo_id"],
            responsible_context["sede_id"],
        )
        session.execute(
            text("UPDATE programa_version SET docente_responsable_id = :responsible_id WHERE id = :id"),
            {"responsible_id": responsible_id, "id": version_id},
        )
    elif section == "competencias":
        if isinstance(content, dict):
            content = [
                {"tipo": "general", "descripcion": line.strip()}
                for line in str(content.get("general", "")).splitlines()
                if line.strip()
            ] + [
                {"tipo": "especifica", "descripcion": line.strip()}
                for line in str(content.get("especificas", "")).splitlines()
                if line.strip()
            ]
        session.execute(text("DELETE FROM programa_competencia WHERE programa_version_id = :id"), {"id": version_id})
        for index, item in enumerate(content, 1):
            session.execute(
                text("""INSERT INTO programa_competencia
                        (programa_version_id, orden, tipo, descripcion)
                        VALUES (:version_id, :orden, :tipo, :descripcion)"""),
                {
                    "version_id": version_id,
                    "orden": item.get("orden", index),
                    "tipo": item["tipo"],
                    "descripcion": item["descripcion"],
                },
            )
    elif section == "bibliografia":
        if isinstance(content, dict):
            reference = str(content.get("texto", "")).strip()
            content = [{"tipo": "basica", "referencia": reference}] if reference else []
        session.execute(text("DELETE FROM programa_bibliografia WHERE programa_version_id = :id"), {"id": version_id})
        for index, item in enumerate(content, 1):
            session.execute(
                text("""INSERT INTO programa_bibliografia
                        (programa_version_id, orden, tipo, referencia, isbn, url)
                        VALUES (:version_id, :orden, :tipo, :referencia, :isbn, :url)"""),
                {
                    "version_id": version_id,
                    "orden": item.get("orden", index),
                    "tipo": item["tipo"],
                    "referencia": item["referencia"],
                    "isbn": item.get("isbn"),
                    "url": item.get("url"),
                },
            )
    elif section == "evaluacion":
        if isinstance(content, dict):
            entries = []
            for key, value in content.items():
                if value is None or not str(value).strip():
                    continue
                try:
                    percent = Decimal(str(value).replace("%", "").strip())
                except (InvalidOperation, ValueError):
                    raise ApiError(
                        422,
                        "VALIDATION_ERROR",
                        "La ponderación de la evaluación debe ser numérica.",
                        {key: "Escribe un porcentaje válido."},
                    )
                if percent > 0:
                    entries.append({"nombre": key, "ponderacion": percent})
            content = entries
        _validate_evaluations(content)
        session.execute(text("DELETE FROM programa_evaluacion WHERE programa_version_id = :id"), {"id": version_id})
        for index, item in enumerate(content, 1):
            session.execute(
                text("""INSERT INTO programa_evaluacion
                        (programa_version_id, orden, nombre, descripcion, ponderacion, semana)
                        VALUES (:version_id, :orden, :nombre, :descripcion, :ponderacion, :semana)"""),
                {
                    "version_id": version_id,
                    "orden": item.get("orden", index),
                    "nombre": item["nombre"],
                    "descripcion": item.get("descripcion"),
                    "ponderacion": item["ponderacion"],
                    "semana": item.get("semana"),
                },
            )
    elif section == "prerrequisitos":
        if isinstance(content, dict):
            content = content.get("asignaturas", [])
        session.execute(text("DELETE FROM programa_prerrequisito WHERE programa_version_id = :id"), {"id": version_id})
        for index, item in enumerate(content, 1):
            course_id = item.get("curso_id")
            if not course_id and item.get("codigo"):
                course = _one(
                    session,
                    "SELECT id FROM curso WHERE codigo = :codigo",
                    {"codigo": item["codigo"]},
                )
                course_id = course["id"] if course else None
            if not course_id:
                raise ApiError(
                    422,
                    "VALIDATION_ERROR",
                    "El prerrequisito debe corresponder a un curso de G1.",
                    {f"prerrequisitos[{index - 1}].codigo": "Código inexistente en el catálogo de cursos."},
                )
            session.execute(
                text("""INSERT INTO programa_prerrequisito
                        (programa_version_id, curso_requerido_id, orden, tipo)
                        VALUES (:version_id, :curso_id, :orden, :tipo)"""),
                {
                    "version_id": version_id,
                    "curso_id": course_id,
                    "orden": item.get("orden", index),
                    "tipo": item.get("tipo", "obligatorio"),
                },
            )
    elif section == "perfil":
        if isinstance(content, dict):
            content = [content] if content.get("codigo") else []
        session.execute(text("DELETE FROM programa_perfil_egreso WHERE programa_version_id = :id"), {"id": version_id})
        for index, item in enumerate(content, 1):
            profile_id = item.get("perfil_egreso_id")
            if not profile_id and item.get("codigo"):
                profile = _one(
                    session,
                    """SELECT id FROM perfil_egreso WHERE codigo = :codigo
                       AND activo = 1 ORDER BY id LIMIT 1""",
                    {"codigo": item["codigo"]},
                )
                profile_id = profile["id"] if profile else None
            if not profile_id:
                raise ApiError(
                    422,
                    "VALIDATION_ERROR",
                    "Cada rasgo de perfil debe referenciar el catálogo de G1.",
                    {f"perfil[{index - 1}].perfil_egreso_id": "Campo obligatorio."},
                )
            session.execute(
                text("""INSERT INTO programa_perfil_egreso
                        (programa_version_id, orden, perfil_egreso_id, contribucion)
                        VALUES (:version_id, :orden, :profile_id, :contribution)"""),
                {
                    "version_id": version_id,
                    "orden": item.get("orden", index),
                    "profile_id": profile_id,
                    "contribution": item["contribucion"],
                },
            )
    elif section == "contenidos":
        if isinstance(content, dict):
            lines = [line.strip() for line in str(content.get("texto", "")).splitlines() if line.strip()]
            content = [{
                "titulo": "Contenido",
                "items": [{"item": line} for line in lines],
            }] if lines else []
        session.execute(
            text("""DELETE ui FROM programa_unidad_item ui
                    JOIN programa_unidad pu ON pu.id = ui.programa_unidad_id
                    WHERE pu.programa_version_id = :id"""),
            {"id": version_id},
        )
        session.execute(text("DELETE FROM programa_unidad WHERE programa_version_id = :id"), {"id": version_id})
        unit_ids = []
        for index, unit in enumerate(content, 1):
            result = session.execute(
                text("""INSERT INTO programa_unidad
                        (programa_version_id, orden, titulo, horas)
                        VALUES (:version_id, :orden, :titulo, :horas)"""),
                {
                    "version_id": version_id,
                    "orden": unit.get("orden", index),
                    "titulo": unit["titulo"],
                    "horas": unit.get("horas"),
                },
            )
            unit_ids.append((result.lastrowid, unit))
        for unit_id, unit in unit_ids:
            for item_order, item in enumerate(unit.get("items", []), 1):
                session.execute(
                    text("""INSERT INTO programa_unidad_item
                            (programa_unidad_id, orden, item, descripcion, actividad, evidencia, punteo)
                            VALUES (:unit_id, :orden, :item, :descripcion, :actividad, :evidencia, :punteo)"""),
                    {
                        "unit_id": unit_id,
                        "orden": item.get("orden", item_order),
                        "item": item["item"],
                        "descripcion": item.get("descripcion"),
                        "actividad": item.get("actividad"),
                        "evidencia": item.get("evidencia"),
                        "punteo": item.get("punteo"),
                    },
                )


# Consultas para listar programas y revisar cambios entre versiones.
def list_programs(
    session: Session,
    page: int,
    per_page: int,
    *,
    curso_id: int | None = None,
    periodo_id: int | None = None,
    sede_id: int | None = None,
    estado: str | None = None,
    version: int | None = None,
    docente_responsable_id: int | None = None,
):
    """Lista programas/versiones paginados y aplica los filtros solicitados."""
    conditions = []
    params = {"limit": per_page, "offset": (page - 1) * per_page}
    for column, value, parameter in (
        ("pc.curso_id", curso_id, "curso_id"),
        ("pv.periodo_id", periodo_id, "periodo_id"),
        ("pc.sede_id", sede_id, "sede_id"),
        ("pv.estado_codigo", estado, "estado"),
        ("pv.numero_version", version, "version"),
    ):
        if value is not None:
            conditions.append(f"{column} = :{parameter}")
            params[parameter] = value
    if docente_responsable_id is not None:
        conditions.append("pv.docente_responsable_id = :docente_responsable_id")
        params["docente_responsable_id"] = docente_responsable_id
    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    from_clause = """
        FROM programa_curso pc
        JOIN curso c ON c.id = pc.curso_id
        JOIN sede s ON s.id = pc.sede_id
        JOIN modalidad m ON m.id = pc.modalidad_id
        LEFT JOIN programa_version pv ON pv.programa_curso_id = pc.id
        LEFT JOIN periodo p ON p.id = pv.periodo_id
    """
    total = session.execute(
        text(f"SELECT COUNT(*) {from_clause}{where_clause}"),
        {key: value for key, value in params.items() if key not in {"limit", "offset"}},
    ).scalar_one()
    rows = _all(
        session,
        f"""SELECT pc.id, pc.curso_id, pc.sede_id, pc.modalidad_id, pc.activo,
                   c.codigo, c.nombre AS asignatura, s.nombre AS sede,
                   m.nombre AS modalidad, pv.id AS programa_version_id,
                   pv.numero_version, p.codigo AS periodo, pv.estado_codigo AS estado,
                   (SELECT MAX(v.numero_version) FROM programa_version v
                    WHERE v.programa_curso_id = pc.id AND v.estado_codigo = 'authorized')
                    AS version_actual,
                   (SELECT p_vigente.codigo
                    FROM programa_version v_vigente
                    JOIN periodo p_vigente ON p_vigente.id = v_vigente.periodo_id
                    WHERE v_vigente.programa_curso_id = pc.id
                      AND v_vigente.estado_codigo = 'authorized'
                    ORDER BY v_vigente.numero_version DESC, v_vigente.periodo_id DESC
                    LIMIT 1) AS periodo_vigente
            {from_clause}{where_clause}
            ORDER BY pc.id DESC, pv.periodo_id DESC, pv.numero_version DESC
            LIMIT :limit OFFSET :offset""",
        params,
    )
    return {"page": page, "per_page": per_page, "total": total, "data": json_value(rows)}


def get_program(session: Session, program_id: int):
    """Trae los datos del programa y su historial de versiones."""
    program = _program_row(session, program_id)
    if not program:
        raise ApiError(404, "NOT_FOUND", "Programa no encontrado.")
    versions = _all(
        session,
        MAIN_SELECT + " WHERE pv.programa_curso_id = :id ORDER BY pv.numero_version",
        {"id": program_id},
    )
    return {
        "programa": json_value(program),
        "versiones": [_serialize_version(session, version) for version in versions],
    }


def get_version(session: Session, version_id: int):
    """Trae una versión junto con el contenido de sus secciones."""
    return _serialize_version(session, _require_version(session, version_id))


def _flatten(value, prefix=""):
    """Convierte datos anidados en campos simples para comparar versiones."""
    if isinstance(value, dict):
        flattened = {}
        for key, child in value.items():
            flattened.update(_flatten(child, f"{prefix}.{key}" if prefix else key))
        return flattened
    if isinstance(value, list):
        flattened = {}
        for index, child in enumerate(value):
            flattened.update(_flatten(child, f"{prefix}[{index}]"))
        return flattened
    return {prefix: value} if prefix else {}


def get_changes(session: Session, version_id: int):
    """Muestra qué cambió frente a la versión anterior."""
    current = _require_version(session, version_id)
    previous = _one(
        session,
        MAIN_SELECT + """ WHERE pv.programa_curso_id = :program_id
                          AND pv.periodo_id = :period_id
                          AND pv.numero_version < :number
                          ORDER BY pv.numero_version DESC LIMIT 1""",
        {
            "program_id": current["programa_curso_id"],
            "period_id": current["periodo_id"],
            "number": current["numero_version"],
        },
    )
    if previous is None:
        return {"version": current["id"], "version_anterior": None, "cambios": []}
    before = _flatten(_load_sections(session, previous))
    after = _flatten(_load_sections(session, current))
    before["estado"] = previous["estado_codigo"]
    after["estado"] = current["estado_codigo"]
    return {
        "version": current["id"],
        "version_anterior": previous["id"],
        "cambios": [
            {
                "campo": key,
                "anterior": json_value(before.get(key)),
                "actual": json_value(after.get(key)),
            }
            for key in sorted(set(before) | set(after))
            if before.get(key) != after.get(key)
        ],
    }


# Validación y persistencia de cambios en una versión.
def _validate_sections(sections: dict):
    """Revisa que las secciones existan y tengan datos en el formato esperado."""
    if not isinstance(sections, dict):
        raise ApiError(422, "VALIDATION_ERROR", "Las secciones deben ser un objeto.", {"secciones": "Se requiere un objeto."})
    allowed = {
        "general", "descripcion", "prerrequisitos", "competencias",
        "perfil", "metodologia", "contenidos", "bibliografia", "evaluacion", "responsables",
    }
    unknown = set(sections) - allowed
    if unknown:
        raise ApiError(422, "VALIDATION_ERROR", "Hay secciones desconocidas.", {"secciones": sorted(unknown)})
    for name, body in sections.items():
        if not isinstance(body, dict) or not isinstance(body.get("contenido"), (dict, list)):
            raise ApiError(422, "VALIDATION_ERROR", "El contenido de sección no es válido.", {name: "contenido debe ser un objeto o una lista."})


def _require_manager_for_responsible_change(
    actor: Actor,
    version: dict,
    content: dict,
) -> None:
    """Solo un gestor puede transferir la asignación de una versión a otro docente."""
    raw_id = content.get("docente_responsable_id")
    if raw_id is None:
        return
    try:
        if isinstance(raw_id, bool) or (
            isinstance(raw_id, float) and not raw_id.is_integer()
        ):
            return
        requested_id = int(raw_id)
    except (TypeError, ValueError):
        return
    current_id = version.get("docente_responsable_id")
    if requested_id != current_id and not has_role(actor, "manager"):
        raise ApiError(
            403,
            "FORBIDDEN",
            "Solo un gestor de programas puede cambiar al docente responsable.",
        )


def update_version(session: Session, actor: Actor, version_id: int, body: dict, section: str | None = None):
    """Guarda cambios en una versión editable y registra quién los hizo.

    Se puede actualizar una sección o varias. El ID y el estado de la versión
    no se pueden cambiar desde la solicitud.
    """
    with session.begin():
        set_database_actor(session, actor)
        row = _require_version(session, version_id, lock=True)
        is_manager = has_role(actor, "manager")
        is_author = has_role(actor, "author")
        is_assigned_teacher = (
            "teacher" in actor.roles
            and actor.id == row.get("docente_responsable_id")
        )
        if not is_manager and not (is_author and is_assigned_teacher):
            raise ApiError(
                403,
                "FORBIDDEN",
                "Solo un gestor de programas o el docente responsable puede editarla.",
            )
        editable(row["estado_codigo"])
        if section:
            if section not in {
                "general", "descripcion", "prerrequisitos", "competencias",
                "perfil", "metodologia", "contenidos", "bibliografia", "evaluacion", "responsables",
            }:
                raise ApiError(404, "NOT_FOUND", "Sección de programa no reconocida.")
            content = body.get("contenido")
            if not isinstance(content, (dict, list)):
                raise ApiError(422, "VALIDATION_ERROR", "El contenido debe ser un objeto o una lista.", {"contenido": "Formato no válido."})
            if section == "responsables" and isinstance(content, dict):
                _require_manager_for_responsible_change(actor, row, content)
            _save_section(
                session,
                version_id,
                section,
                content,
                actor.id,
                row,
            )
        else:
            protected = {"id", "programa_id", "programa_curso_id", "numero_version", "estado", "version_origen_id"}
            if protected.intersection(body):
                raise ApiError(422, "VALIDATION_ERROR", "No puedes modificar la identidad ni el estado de la versión.", {"body": "Campo protegido."})
            if "secciones" in body:
                _validate_sections(body["secciones"])
                for name, value in body["secciones"].items():
                    if name == "responsables":
                        _require_manager_for_responsible_change(
                            actor,
                            row,
                            value["contenido"],
                        )
                    _save_section(
                        session,
                        version_id,
                        name,
                        value["contenido"],
                        actor.id,
                        row,
                    )
            if "resumen_cambios" in body:
                session.execute(
                    text("UPDATE programa_version SET resumen_cambios = :value WHERE id = :id"),
                    {"value": body["resumen_cambios"], "id": version_id},
                )
        session.execute(text("UPDATE programa_version SET actualizado_en = CURRENT_TIMESTAMP(3) WHERE id = :id"), {"id": version_id})
        result = _serialize_version(session, _require_version(session, version_id))
    return result


# Reglas de envío y cambios de estado de las versiones.
def _validate_for_submit(session: Session, version_id: int, row: dict):
    """Revisa que el programa esté completo antes de enviarlo a revisión.

    Por ejemplo, debe tener nombre y período, y las evaluaciones deben sumar 100.
    """
    missing = []
    if not row.get("nombre"):
        missing.append("nombre")
    if not row.get("periodo_id"):
        missing.append("periodo_id")
    evaluations = _all(
        session,
        "SELECT ponderacion FROM programa_evaluacion WHERE programa_version_id = :id",
        {"id": version_id},
    )
    if sum(Decimal(str(item["ponderacion"])) for item in evaluations) != Decimal("100"):
        missing.append("evaluacion.ponderacion (debe sumar 100)")
    if missing:
        raise ApiError(422, "VALIDATION_ERROR", "Completa los campos requeridos antes de enviar.", {field: "Campo obligatorio o inválido." for field in missing})


def transition(session: Session, actor: Actor, version_id: int, action: str, comment: str | None = None):
    """Cambia el estado de la versión cuando la acción está permitida.

    Antes de guardar el cambio, revisa el estado actual, el usuario y los datos
    necesarios para enviar, revisar, devolver, aprobar o autorizar.
    """
    with session.begin():
        set_database_actor(session, actor)
        row = _require_version(session, version_id, lock=True)
        current = row["estado_codigo"]
        new_status = next_status(action, current)

        if action == "submit":
            _require_teacher_is_responsible(actor, row.get("docente_responsable_id"))
            _validate_for_submit(session, version_id, row)
        if action == "return" and not (comment and comment.strip()):
            raise ApiError(422, "VALIDATION_ERROR", "La devolución requiere una observación.", {"comentario": "Este campo es obligatorio."})

        if action == "authorize":
            authorized = _all(
                session,
                """SELECT programa_curso_id, periodo_id, estado_codigo
                   FROM programa_version
                   WHERE programa_curso_id = :program_id AND periodo_id = :period_id
                     AND estado_codigo = 'authorized' FOR UPDATE""",
                {"program_id": row["programa_curso_id"], "period_id": row["periodo_id"]},
            )
            from .domain import ensure_single_authorized

            ensure_single_authorized(
                authorized,
                row["programa_curso_id"],
                row["periodo_id"],
            )
            session.execute(
                text("CALL sp_autorizar_version(:version_id, :actor_id, :comment)"),
                {"version_id": version_id, "actor_id": actor.id, "comment": comment},
            ).close()
            return get_version(session, version_id)

        if action == "review":
            session.execute(
                text("UPDATE programa_version SET revisor_id = :actor_id WHERE id = :id"),
                {"actor_id": actor.id, "id": version_id},
            )
        session.execute(
            text("UPDATE programa_version SET estado_codigo = :status WHERE id = :id"),
            {"status": new_status, "id": version_id},
        )
        session.execute(
            text("""INSERT INTO programa_aprobacion
                    (programa_version_id, actor_id, estado_anterior, estado_nuevo, comentario)
                    VALUES (:version_id, :actor_id, :previous, :status, :comment)"""),
            {
                "version_id": version_id,
                "actor_id": actor.id,
                "previous": current,
                "status": new_status,
                "comment": comment,
            },
        )
        result = _serialize_version(session, _require_version(session, version_id))
    return result


# Preparación y generación de los datos del PDF autorizado.
def _version_content_for_pdf(session: Session, version_id: int):
    """Busca los datos del programa y la aprobación que aparecerán en el PDF."""
    row = _require_version(session, version_id)
    if row["estado_codigo"] not in {"authorized", "superseded"}:
        raise ApiError(409, "CONFLICT", "El PDF solo se genera para versiones autorizadas.")
    if row["estado_codigo"] == "authorized" and _one(
        session,
        """SELECT programa_version_id FROM v_programa_vigente
           WHERE programa_version_id = :id""",
        {"id": version_id},
    ) is None:
        raise ApiError(409, "CONFLICT", "La versión no aparece como autorizada en G1.")
    version = _serialize_version(session, row)
    program = _program_row(session, row["programa_curso_id"])
    approval = _one(
        session,
        """SELECT id, creado_en, comentario FROM programa_aprobacion
           WHERE programa_version_id = :id AND estado_nuevo = 'authorized'
           ORDER BY creado_en DESC LIMIT 1""",
        {"id": version_id},
    )
    if approval is None:
        raise ApiError(409, "CONFLICT", "No se encontró la autorización de origen del PDF.")
    version["autorizacion"] = json_value(approval)
    return json_value(program), version, approval


def generate_pdf_data(session: Session, version_id: int, actor: Actor):
    """Arma el PDF y calcula su huella para identificar el archivo generado."""
    from .pdf import build_pdf

    program, version, approval = _version_content_for_pdf(session, version_id)
    pdf = build_pdf(program, version, approval)
    return pdf, hashlib.sha256(pdf).hexdigest(), program, version


def _assignment_origin_id(body: dict) -> int | None:
    """Valida el ID opcional de la asignación G3 que originó la versión."""
    raw_id = body.get("tarea_destinatario_origen_id")
    if raw_id is None:
        return None
    try:
        if isinstance(raw_id, bool) or (
            isinstance(raw_id, float) and not raw_id.is_integer()
        ):
            raise ValueError
        assignment_id = int(raw_id)
    except (TypeError, ValueError):
        assignment_id = 0
    if assignment_id <= 0:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "La asignación de origen debe ser un identificador válido.",
            {"tarea_destinatario_origen_id": "Usa un entero positivo."},
        )
    return assignment_id


def _validate_responsible_teacher(
    session: Session,
    raw_id,
    course_id: int,
    period_id: int,
    campus_id: int,
) -> int:
    """Requiere que el responsable esté asignado al mismo curso, período y sede en G1."""
    try:
        if isinstance(raw_id, bool) or (
            isinstance(raw_id, float) and not raw_id.is_integer()
        ):
            raise ValueError
        teacher_id = int(raw_id)
    except (TypeError, ValueError):
        teacher_id = 0
    if teacher_id <= 0:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "El docente responsable debe ser un identificador válido.",
            {"docente_responsable_id": "Usa un entero positivo."},
        )

    assigned = _one(
        session,
        """SELECT dc.usuario_id FROM docente_curso dc
           JOIN usuario u ON u.id = dc.usuario_id
           WHERE dc.usuario_id = :teacher_id AND dc.curso_id = :course_id
             AND dc.periodo_id = :period_id AND dc.sede_id = :campus_id
             AND dc.activo = 1 AND u.activo = 1 AND u.eliminado_en IS NULL""",
        {
            "teacher_id": teacher_id,
            "course_id": course_id,
            "period_id": period_id,
            "campus_id": campus_id,
        },
    )
    if assigned is None:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "El docente no está asignado al curso, período y sede seleccionados.",
            {"docente_responsable_id": "Debe existir una asignación activa en docente_curso de G1."},
        )
    return teacher_id


def _require_teacher_is_responsible(actor: Actor, responsible_id: int | None) -> None:
    if (
        "teacher" in actor.roles
        and "coordinator" not in actor.roles
        and actor.id != responsible_id
    ):
        raise ApiError(
            403,
            "FORBIDDEN",
            "Un docente solo puede trabajar en versiones donde figura como responsable.",
        )


# Creación de programas y versiones, y registro del PDF generado.
def create_program(session: Session, actor: Actor, body: dict):
    """Guarda un programa nuevo y crea su primera versión en borrador."""
    required_ids = ("curso_id", "sede_id", "modalidad_id", "periodo_id")
    missing = [key for key in required_ids if not body.get(key)]
    if missing:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Faltan identificadores del catálogo de G1.",
            {key: "Campo obligatorio." for key in missing},
        )
    assignment_id = _assignment_origin_id(body)
    with session.begin():
        set_database_actor(session, actor)
        responsible_id = body.get("docente_responsable_id")
        sections = body.get("secciones")
        responsible_section = sections.get("responsables") if isinstance(sections, dict) else None
        responsible_content = (
            responsible_section.get("contenido")
            if isinstance(responsible_section, dict)
            else None
        )
        section_responsible_id = (
            responsible_content.get("docente_responsable_id")
            if isinstance(responsible_content, dict)
            else None
        )
        try:
            top_level_id = int(responsible_id) if responsible_id is not None else None
            section_id = int(section_responsible_id) if section_responsible_id is not None else None
        except (TypeError, ValueError):
            top_level_id = section_id = None
        if (
            isinstance(responsible_id, bool)
            or isinstance(section_responsible_id, bool)
            or top_level_id is not None
            and section_id is not None
            and top_level_id != section_id
        ):
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "El docente responsable debe ser el mismo en el encabezado y la sección.",
                {"docente_responsable_id": "Los identificadores no coinciden."},
            )
        if responsible_id is None:
            responsible_id = section_responsible_id
        if responsible_id is None and "teacher" in actor.roles:
            responsible_id = actor.id
        if responsible_id is not None:
            responsible_id = _validate_responsible_teacher(
                session,
                responsible_id,
                body["curso_id"],
                body["periodo_id"],
                body["sede_id"],
            )
            _require_teacher_is_responsible(actor, responsible_id)
        context = _one(
            session,
            """SELECT pc.id, pc.curso_id FROM programa_curso pc
               WHERE pc.curso_id = :curso_id AND pc.sede_id = :sede_id
                 AND pc.modalidad_id = :modalidad_id FOR UPDATE""",
            {
                "curso_id": body["curso_id"],
                "sede_id": body["sede_id"],
                "modalidad_id": body["modalidad_id"],
            },
        )
        if context:
            program_id = context["id"]
        else:
            result = session.execute(
                text("""INSERT INTO programa_curso
                        (curso_id, sede_id, modalidad_id, creado_por)
                        VALUES (:curso_id, :sede_id, :modalidad_id, :actor_id)"""),
                {
                    "curso_id": body["curso_id"],
                    "sede_id": body["sede_id"],
                    "modalidad_id": body["modalidad_id"],
                    "actor_id": actor.id,
                },
            )
            program_id = result.lastrowid
        existing_period_version = session.execute(
            text("""SELECT MAX(numero_version) FROM programa_version
                    WHERE programa_curso_id = :id AND periodo_id = :periodo_id"""),
            {"id": program_id, "periodo_id": body["periodo_id"]},
        ).scalar_one()
        if existing_period_version is not None:
            raise ApiError(
                409,
                "CONFLICT",
                "El programa ya tiene una versión para este período; usa la ruta de versiones.",
            )
        next_version = session.execute(
            text("""SELECT COALESCE(MAX(numero_version), 0) + 1
                    FROM programa_version WHERE programa_curso_id = :id"""),
            {"id": program_id},
        ).scalar_one()
        result = session.execute(
            text("""INSERT INTO programa_version
                    (programa_curso_id, numero_version, periodo_id, estado_codigo,
                     nombre, descripcion, programa_academico,
                     departamento, nivel, pensum, horas_clase_semanal,
                     docente_responsable_id, tarea_destinatario_origen_id, creado_por)
                    VALUES (:program_id, :number, :period_id, 'draft',
                            :name, :description, :program,
                            :department, :level, :pensum, :hours, :teacher,
                            :assignment_id, :actor_id)"""),
            {
                "program_id": program_id,
                "number": next_version,
                "period_id": body["periodo_id"],
                "name": body.get("nombre") or body.get("asignatura") or "Programa de curso",
                "description": body.get("descripcion"),
                "program": body.get("programa_academico"),
                "department": body.get("departamento"),
                "level": body.get("nivel"),
                "pensum": body.get("pensum"),
                "hours": body.get("horas_clase_semanal"),
                "teacher": responsible_id,
                "assignment_id": assignment_id,
                "actor_id": actor.id,
            },
        )
        version_id = result.lastrowid
        if body.get("secciones"):
            _validate_sections(body["secciones"])
            for name, value in body["secciones"].items():
                _save_section(
                    session,
                    version_id,
                    name,
                    value["contenido"],
                    actor.id,
                    {
                        "curso_id": body["curso_id"],
                        "periodo_id": body["periodo_id"],
                        "sede_id": body["sede_id"],
                    },
                )
        created = _serialize_version(session, _require_version(session, version_id))
    return {"programa": _program_row(session, program_id), "version": created}


def create_version(session: Session, actor: Actor, program_id: int, body: dict):
    """Abre una versión nueva copiando los datos de una versión autorizada."""
    period_id = body.get("periodo_id")
    if not period_id:
        raise ApiError(422, "VALIDATION_ERROR", "Falta el período académico.", {"periodo_id": "Campo obligatorio."})
    assignment_id = _assignment_origin_id(body)
    with session.begin():
        set_database_actor(session, actor)
        program = _program_row(session, program_id)
        if program is None:
            raise ApiError(404, "NOT_FOUND", "Programa no encontrado.")
        source = _one(
            session,
            MAIN_SELECT + """ WHERE pv.programa_curso_id = :program_id
                              AND pv.periodo_id = :period_id
                              AND pv.estado_codigo = 'authorized'
                              ORDER BY pv.numero_version DESC LIMIT 1 FOR UPDATE""",
            {"program_id": program_id, "period_id": period_id},
        )
        latest = session.execute(
            text("""SELECT MAX(numero_version) FROM programa_version
                    WHERE programa_curso_id = :program_id"""),
            {"program_id": program_id},
        ).scalar_one()
        if source is None:
            raise ApiError(409, "CONFLICT", "Solo se puede clonar una versión autorizada.")
        result = session.execute(
            text("""INSERT INTO programa_version
                    (programa_curso_id, numero_version, periodo_id, estado_codigo,
                     version_origen_id, nombre, descripcion, resumen_cambios,
                     unidad_academica_id, programa_academico, departamento, nivel,
                     area_id, pensum, horas_clase_semanal,
                     docente_responsable_id, tarea_destinatario_origen_id, creado_por)
                    VALUES (:program_id, :number, :period_id, 'draft',
                            :source_id, :name, :description, :summary,
                            :unit_id, :academic_program, :department, :level,
                            :area_id, :pensum, :hours, :responsible_id,
                            :assignment_id, :actor_id)"""),
            {
                "program_id": program_id,
                "number": (latest or 0) + 1,
                "period_id": period_id,
                "source_id": source["id"] if source and body.get("clonar", True) else None,
                "name": (source or {}).get("nombre", program["asignatura"]),
                "description": (source or {}).get("descripcion"),
                "summary": body.get("resumen_cambios"),
                "unit_id": (source or {}).get("unidad_academica_id"),
                "academic_program": (source or {}).get("programa_academico"),
                "department": (source or {}).get("departamento"),
                "level": (source or {}).get("nivel"),
                "area_id": (source or {}).get("area_id"),
                "pensum": (source or {}).get("pensum"),
                "hours": (source or {}).get("horas_clase_semanal"),
                "responsible_id": (source or {}).get("docente_responsable_id", actor.id),
                "assignment_id": (
                    assignment_id if "tarea_destinatario_origen_id" in body
                    else (source or {}).get("tarea_destinatario_origen_id")
                ),
                "actor_id": actor.id,
            },
        )
        version_id = result.lastrowid
        if source and body.get("clonar", True):
            for section_name, value in _load_sections(session, source).items():
                if section_name != "responsables":
                    _save_section(session, version_id, section_name, value["contenido"], actor.id)
        version = _serialize_version(session, _require_version(session, version_id))
    return version


def record_pdf(session: Session, actor: Actor, version_id: int, pdf: bytes, digest: str):
    """Guarda la huella del PDF autorizado, pero no el archivo.

    G2 se encarga del archivo. Este registro sirve para identificarlo y no
    reemplaza una huella que ya se haya guardado.
    """
    try:
        set_database_actor(session, actor)
        row = _require_version(session, version_id, lock=True)
        if row["estado_codigo"] not in {"authorized", "superseded"}:
            raise ApiError(409, "CONFLICT", "El PDF solo se guarda para versiones autorizadas.")
        if row["estado_codigo"] == "authorized":
            session.execute(
                text("""UPDATE programa_version
                        SET pdf_hash = :digest, pdf_generado_en = CURRENT_TIMESTAMP(3)
                        WHERE id = :id AND pdf_hash IS NULL"""),
                {"digest": digest, "id": version_id},
            )
        session.commit()
    except (SQLAlchemyError, ApiError):
        session.rollback()
        raise
