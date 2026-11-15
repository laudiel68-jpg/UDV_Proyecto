"""Tipos de tarea, borradores, destinatarios, publicación, cancelación y seguimiento.

Dos dialectos (según el tipo de conexión):
    * SQLite (tests): tablas propias tasks / assignments / users / task_types.
    * MySQL (G1):     tarea / tarea_destinatario / usuario(+usuario_rol) / tipo_tarea / workflow.
      Allí la publicación la hace el procedimiento sp_publicar_tarea de G1, los eventos los
      crean sus triggers, y las consultas usan alias para devolver los mismos campos de siempre
      (title, status, due_date...). No se usa '%' en el SQL: pymysql lo interpreta.
"""
import json
from datetime import date

from . import events, transitions
from .db import MySQLConn, set_actor, transaction, utcnow
from .errors import Conflict, Forbidden, NotFound, ValidationFailed
from .matrix import AUTHORITY, COORDINATOR, FLOWS, REVIEWER, STATES, TEACHER

PRIORITIES = ("low", "medium", "high")
EDITABLE_FIELDS = ("type_id", "title", "description", "priority", "due_date",
                   "responsible_id", "reviewer_id")


def _is_mysql(conn) -> bool:
    return isinstance(conn, MySQLConn)


def _roles(actor) -> set:
    return transitions._roles(actor)


# ----------------------------------------------------------------- utilidades
def paginate(page, page_size):
    if not isinstance(page, int) or page < 1:
        raise ValidationFailed("page debe ser un entero >= 1")
    if not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise ValidationFailed("per_page debe estar entre 1 y 100")
    return page_size, (page - 1) * page_size


def _paged(conn, select, frm, params, order, page, page_size):
    limit, offset = paginate(page, page_size)
    total = conn.execute(f"SELECT COUNT(*) {frm}", params).fetchone()[0]
    rows = conn.execute(f"{select} {frm} ORDER BY {order} LIMIT ? OFFSET ?",
                        [*params, limit, offset]).fetchall()
    return {"data": [dict(r) for r in rows], "page": page,
            "per_page": page_size, "total": total}


# ---- G1: una tarea con los nombres y estados de siempre -------------------------------
# status: draft | published | cancelled (en G1 una tarea publicada queda en 'assigned').
# Un borrador cancelado se guarda como eliminación lógica (eliminado_en): la restricción
# ck_tarea_publicada de G1 no permite 'cancelled' sin publicada_en.
_TASK_COLS_MYSQL = (
    "t.id, w.tipo_tarea_id AS type_id, t.titulo AS title,"
    " COALESCE(t.descripcion, '') AS description, t.prioridad AS priority,"
    " CAST(DATE(t.fecha_limite) AS CHAR) AS due_date,"
    " CASE WHEN t.eliminado_en IS NOT NULL THEN 'cancelled'"
    "      WHEN t.estado_codigo IN ('draft', 'cancelled') THEN t.estado_codigo"
    "      ELSE 'published' END AS status,"
    " t.creado_por AS created_by, NULL AS responsible_id, t.revisor_id AS reviewer_id,"
    " t.publicada_en AS published_at,"
    " COALESCE(t.eliminado_en, CASE WHEN t.estado_codigo = 'cancelled'"
    "                              THEN t.actualizado_en END) AS cancelled_at,"
    " t.creado_en AS created_at, t.actualizado_en AS updated_at,"
    " t.alcance, t.sede_destino_id, t.unidad_destino_id, 'standard' AS flow")
_TASK_FROM_MYSQL = "FROM tarea t JOIN workflow w ON w.id = t.workflow_id"

_STATUS_SQL_MYSQL = {
    "draft": "(t.estado_codigo = 'draft' AND t.eliminado_en IS NULL)",
    "published": "(t.estado_codigo NOT IN ('draft', 'cancelled') AND t.eliminado_en IS NULL)",
    "cancelled": "(t.estado_codigo = 'cancelled' OR t.eliminado_en IS NOT NULL)",
}
_INTERNAL_KEYS = ("alcance", "sede_destino_id", "unidad_destino_id")


def _end_of_day(iso_date):
    return f"{iso_date} 23:59:59"


def _rule_from_mysql(conn, d):
    """Reconstruye la regla de destinatarios (all / users / filter) desde las columnas de G1."""
    alcance = d.get("alcance")
    if alcance == "todos":
        return {"mode": "all"}
    if alcance == "seleccion":
        ids = [r["usuario_id"] for r in conn.execute(
            "SELECT usuario_id FROM tarea_seleccion"
            " WHERE tarea_id = ? AND tipo = 'usuario' AND usuario_id IS NOT NULL"
            " ORDER BY usuario_id", (d["id"],)).fetchall()]
        return {"mode": "users", "user_ids": ids}
    if alcance == "sede":
        r = conn.execute("SELECT nombre FROM sede WHERE id = ?", (d["sede_destino_id"],)).fetchone()
        return {"mode": "filter", "campus": r["nombre"] if r else None}
    if alcance == "unidad":
        r = conn.execute("SELECT nombre FROM unidad_academica WHERE id = ?",
                         (d["unidad_destino_id"],)).fetchone()
        return {"mode": "filter", "unit": r["nombre"] if r else None}
    return None      # 'individual' (valor por defecto) = destinatarios sin configurar


def _task_out(row, conn=None):
    d = dict(row)
    if conn is not None and _is_mysql(conn):
        d["recipient_rule"] = _rule_from_mysql(conn, d)
        for k in _INTERNAL_KEYS + ("flow",):
            d.pop(k, None)
        return d
    d["recipient_rule"] = json.loads(d["recipient_rule"]) if d.get("recipient_rule") else None
    return d


def _out(conn, row):
    return _task_out(row, conn)


def _load_task(conn, task_id):
    if _is_mysql(conn):
        row = conn.execute(f"SELECT {_TASK_COLS_MYSQL} {_TASK_FROM_MYSQL} WHERE t.id = ?",
                           (task_id,)).fetchone()
    else:
        row = conn.execute(
            "SELECT t.*, ty.flow AS flow FROM tasks t JOIN task_types ty ON ty.id = t.type_id"
            " WHERE t.id = ?", (task_id,)).fetchone()
    if row is None:
        raise NotFound(f"Tarea {task_id} no existe")
    return row


def _can_manage(actor, task):
    return COORDINATOR in _roles(actor) and actor["id"] in (task["created_by"],
                                                            task["responsible_id"])


def _can_view(actor, task):
    roles = _roles(actor)
    if AUTHORITY in roles:
        return True
    if COORDINATOR in roles and _can_manage(actor, task):
        return True
    if REVIEWER in roles and task["status"] != "draft" and task["reviewer_id"] == actor["id"]:
        return True
    return False


def _parse_due_date(value):
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ValidationFailed("due_date debe ser una fecha ISO 8601 (YYYY-MM-DD)",
                               details={"field": "due_date"})


def _require_user(conn, user_id, field, role=None):
    if _is_mysql(conn):
        sql = ("SELECT u.id FROM usuario u WHERE u.id = ? AND u.activo = 1"
               " AND u.eliminado_en IS NULL")
        params = [user_id]
        if role:
            sql += (" AND EXISTS (SELECT 1 FROM usuario_rol ur JOIN rol r ON r.id = ur.rol_id"
                    " WHERE ur.usuario_id = u.id AND r.codigo = ?)")
            params.append(role)
        row = conn.execute(sql, params).fetchone()
        if row is None:
            raise ValidationFailed(f"{field} no corresponde a un usuario válido",
                                   details={"field": field})
        return
    row = conn.execute("SELECT * FROM users WHERE id = ? AND active = 1", (user_id,)).fetchone()
    if row is None or (role and row["role"] != role):
        raise ValidationFailed(f"{field} no corresponde a un usuario válido",
                               details={"field": field})


def _workflow_for_type(conn, type_id):
    row = conn.execute("SELECT id FROM workflow WHERE tipo_tarea_id = ? AND activo = 1"
                       " ORDER BY id LIMIT 1", (type_id,)).fetchone()
    if row is None:
        raise ValidationFailed("El tipo de tarea no tiene un workflow activo",
                               details={"field": "type_id"})
    return row["id"]


def _call_proc(conn, name, args):
    """CALL a un procedimiento de G1; sus errores (SIGNAL ... (409)/(422)/(404)) se traducen."""
    try:
        conn.execute(f"CALL {name}({', '.join('?' * len(args))})", args)
    except Exception as exc:
        mapped = transitions._translate_db_error(exc)
        if mapped is None:
            raise
        raise mapped from exc


# ---------------------------------------------------------------- task types
def create_task_type(conn, actor, data):
    if not _roles(actor) & {COORDINATOR, AUTHORITY}:
        raise Forbidden("Solo coordinación o autoridad pueden crear tipos de tarea")
    if _is_mysql(conn):
        raise Forbidden("Los tipos de tarea (con su workflow) los administra el Grupo 1")
    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    flow = data.get("flow", "standard")
    if not code or not name:
        raise ValidationFailed("code y name son obligatorios")
    if flow not in FLOWS:
        raise ValidationFailed("flow inválido", details={"field": "flow", "valid": list(FLOWS)})
    with transaction(conn):
        if conn.execute("SELECT 1 FROM task_types WHERE code = ?", (code,)).fetchone():
            raise Conflict(f"Ya existe un tipo con code '{code}'")
        cur = conn.execute(
            "INSERT INTO task_types(code, name, requires_evidence, evidence_type, flow, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (code, name, int(bool(data.get("requires_evidence"))),
             data.get("evidence_type"), flow, utcnow()))
        return dict(conn.execute("SELECT * FROM task_types WHERE id = ?",
                                 (cur.lastrowid,)).fetchone())


def list_task_types(conn, page=1, page_size=20):
    if _is_mysql(conn):
        return _paged(
            conn, "SELECT id, codigo AS code, nombre AS name,"
                  " requiere_archivo AS requires_evidence, extensiones AS evidence_type,"
                  " 'standard' AS flow, creado_en AS created_at",
            "FROM tipo_tarea WHERE activo = 1", [], "id", page, page_size)
    return _paged(conn, "SELECT *", "FROM task_types", [], "id", page, page_size)


# --------------------------------------------------------------------- tasks
def _validate_fields(conn, data):
    mysql = _is_mysql(conn)
    if "title" in data and not (data["title"] or "").strip():
        raise ValidationFailed("title no puede estar vacío", details={"field": "title"})
    if "priority" in data:
        if mysql:
            rows = conn.execute("SELECT codigo FROM prioridad_tarea").fetchall()
            valid = [row[0] for row in rows]
        else:
            valid = list(PRIORITIES)
        if data["priority"] not in valid:
            raise ValidationFailed(
                "priority inválida",
                details={
                    "priority": {
                        "message": "Prioridad no registrada en el catálogo",
                        "valid": valid
                    }
                }
            )
    if "due_date" in data:
        data["due_date"] = _parse_due_date(data["due_date"])
    if "type_id" in data:
        table = "tipo_tarea" if mysql else "task_types"
        if conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (data["type_id"],)).fetchone() is None:
            raise ValidationFailed("type_id no existe", details={"field": "type_id"})
    if data.get("responsible_id") is not None:
        if mysql:
            raise ValidationFailed("responsible_id no existe en la base de G1 (tarea no lo guarda)",
                                   details={"field": "responsible_id"})
        _require_user(conn, data["responsible_id"], "responsible_id", COORDINATOR)
    if data.get("reviewer_id") is not None:
        _require_user(conn, data["reviewer_id"], "reviewer_id", REVIEWER)


def create_task(conn, actor, data):
    if COORDINATOR not in _roles(actor):
        raise Forbidden("Solo un coordinador puede crear tareas")
    data = dict(data)
    unknown = set(data) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValidationFailed("Campos desconocidos", details={"fields": sorted(unknown)})
    for required in ("type_id", "title", "due_date"):
        if data.get(required) in (None, ""):
            raise ValidationFailed(f"{required} es obligatorio", details={"field": required})
    data.setdefault("priority", "medium")
    data.setdefault("description", "")
    with transaction(conn):
        _validate_fields(conn, data)
        if _is_mysql(conn):
            set_actor(conn, actor["id"])
            cur = conn.execute(
                "INSERT INTO tarea(workflow_id, estado_codigo, titulo, descripcion, prioridad,"
                " creado_por, revisor_id, fecha_limite) VALUES (?, 'draft', ?,?,?,?,?,?)",
                (_workflow_for_type(conn, data["type_id"]), data["title"].strip(),
                 data["description"], data["priority"], actor["id"],
                 data.get("reviewer_id"), _end_of_day(data["due_date"])))
            return _out(conn, _load_task(conn, cur.lastrowid))
        now = utcnow()
        cur = conn.execute(
            "INSERT INTO tasks(type_id, title, description, priority, due_date, status,"
            " created_by, responsible_id, reviewer_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?, 'draft', ?,?,?,?,?)",
            (data["type_id"], data["title"].strip(), data["description"], data["priority"],
             data["due_date"], actor["id"], data.get("responsible_id"),
             data.get("reviewer_id"), now, now))
        return _out(conn, _load_task(conn, cur.lastrowid))


def get_task(conn, actor, task_id):
    task = _load_task(conn, task_id)
    if not _can_view(actor, task):
        raise Forbidden("No tienes acceso a esta tarea")
    return _out(conn, task)


def _list_tasks_mysql(conn, actor, status, page, page_size):
    roles = _roles(actor)
    where, params = [], []
    if AUTHORITY not in roles:
        clauses = []
        if COORDINATOR in roles:
            clauses.append("t.creado_por = ?")
            params.append(actor["id"])
        if REVIEWER in roles:
            clauses.append("(t.estado_codigo <> 'draft' AND t.revisor_id = ?)")
            params.append(actor["id"])
        if not clauses:
            raise Forbidden("Tu rol no puede listar tareas")
        where.append("(" + " OR ".join(clauses) + ")")
    if status:
        if status not in _STATUS_SQL_MYSQL:
            raise ValidationFailed("status inválido")
        where.append(_STATUS_SQL_MYSQL[status])
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    res = _paged(conn, f"SELECT {_TASK_COLS_MYSQL}", f"{_TASK_FROM_MYSQL} {clause}", params,
                 "t.id DESC", page, page_size)
    res["data"] = [_task_out(item, conn) for item in res["data"]]
    return res


def list_tasks(conn, actor, status=None, page=1, page_size=20):
    if _is_mysql(conn):
        return _list_tasks_mysql(conn, actor, status, page, page_size)
    where, params = [], []
    if actor["role"] == COORDINATOR:
        where.append("(t.created_by = ? OR t.responsible_id = ?)")
        params += [actor["id"], actor["id"]]
    elif actor["role"] == REVIEWER:
        where.append("t.status != 'draft' AND t.reviewer_id = ?")
        params.append(actor["id"])
    elif actor["role"] != AUTHORITY:
        raise Forbidden("Tu rol no puede listar tareas")
    if status:
        if status not in ("draft", "published", "cancelled"):
            raise ValidationFailed("status inválido")
        where.append("t.status = ?")
        params.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    res = _paged(conn, "SELECT t.*", f"FROM tasks t {clause}", params, "t.id DESC",
                 page, page_size)
    for item in res["data"]:
        item["recipient_rule"] = (json.loads(item["recipient_rule"])
                                  if item["recipient_rule"] else None)
    return res


def update_task(conn, actor, task_id, changes):
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValidationFailed("Campos no editables", details={"fields": sorted(unknown)})
    with transaction(conn):
        task = _load_task(conn, task_id)
        if not _can_manage(actor, task):
            raise Forbidden("No eres el coordinador autorizado de esta tarea")
        if task["status"] != "draft":
            raise Conflict("Solo se puede editar una tarea en borrador", code="NOT_DRAFT")
        changes = dict(changes)
        _validate_fields(conn, changes)
        if changes and _is_mysql(conn):
            set_actor(conn, actor["id"])
            names = {"title": "titulo", "description": "descripcion",
                     "priority": "prioridad", "reviewer_id": "revisor_id"}
            sets, values = [], []
            for key, value in changes.items():
                if key == "type_id":
                    sets.append("workflow_id = ?")
                    values.append(_workflow_for_type(conn, value))
                elif key == "due_date":
                    sets.append("fecha_limite = ?")
                    values.append(_end_of_day(value))
                elif key in names:
                    sets.append(f"{names[key]} = ?")
                    values.append(value)
                # responsible_id=None se ignora: G1 no tiene esa columna
            if sets:
                conn.execute(f"UPDATE tarea SET {', '.join(sets)} WHERE id = ?", [*values, task_id])
        elif changes:
            sets = ", ".join(f"{k} = ?" for k in changes)
            conn.execute(f"UPDATE tasks SET {sets}, updated_at = ? WHERE id = ?",
                         [*changes.values(), utcnow(), task_id])
        return _out(conn, _load_task(conn, task_id))


# ---------------------------------------------------------------- recipients
def _normalize_rule(conn, rule):
    mode = (rule or {}).get("mode")
    if mode == "all":
        return {"mode": "all"}
    if mode == "users":           # un docente o una lista de docentes
        ids = rule.get("user_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
            raise ValidationFailed("user_ids debe ser una lista no vacía de enteros")
        ids = sorted(set(ids))
        valid = {r["id"] for r in conn.execute(
            f"SELECT id FROM users WHERE role = 'teacher' AND active = 1 "
            f"AND id IN ({','.join('?' * len(ids))})", ids)}
        invalid = [i for i in ids if i not in valid]
        if invalid:
            raise ValidationFailed("Hay usuarios que no son docentes activos",
                                   details={"invalid_user_ids": invalid})
        return {"mode": "users", "user_ids": ids}
    if mode == "filter":          # filtro institucional
        campus, unit = rule.get("campus"), rule.get("unit")
        if not campus and not unit:
            raise ValidationFailed("El filtro requiere campus (sede) y/o unit (unidad)")
        out = {"mode": "filter"}
        if campus:
            out["campus"] = campus
        if unit:
            out["unit"] = unit
        return out
    raise ValidationFailed("mode inválido", details={"valid": ["users", "all", "filter"]})


def resolve_recipients(conn, rule):
    """Docentes elegibles HOY para la regla guardada (activos, rol docente, sin duplicados)."""
    sql, params = "SELECT id FROM users WHERE role = 'teacher' AND active = 1", []
    if rule["mode"] == "users":
        sql += f" AND id IN ({','.join('?' * len(rule['user_ids']))})"
        params += rule["user_ids"]
    elif rule["mode"] == "filter":
        for col in ("campus", "unit"):
            if rule.get(col):
                sql += f" AND {col} = ?"
                params.append(rule[col])
    return [r["id"] for r in conn.execute(sql + " ORDER BY id", params)]


# ---- G1: la regla se guarda en tarea.alcance (+ ids) y tarea_seleccion ----------------
_TEACHERS_MYSQL = (
    "FROM usuario u JOIN usuario_rol ur ON ur.usuario_id = u.id JOIN rol r ON r.id = ur.rol_id"
    " LEFT JOIN unidad_academica ua ON ua.id = u.unidad_academica_id"
    " WHERE r.codigo = 'teacher' AND u.activo = 1 AND u.eliminado_en IS NULL")


def _lookup_mysql(conn, table, text):
    """Busca una sede o unidad por código o nombre."""
    row = conn.execute(f"SELECT * FROM {table} WHERE (codigo = ? OR nombre = ?) AND activo = 1",
                       (text, text)).fetchone()
    return row


def _normalize_rule_mysql(conn, rule):
    """Devuelve (alcance, sede_id, unidad_id, user_ids, regla_normalizada) para G1."""
    mode = (rule or {}).get("mode")
    if mode == "all":
        return "todos", None, None, [], {"mode": "all"}
    if mode == "users":
        ids = rule.get("user_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
            raise ValidationFailed("user_ids debe ser una lista no vacía de enteros")
        ids = sorted(set(ids))
        valid = {r["id"] for r in conn.execute(
            f"SELECT DISTINCT u.id {_TEACHERS_MYSQL} AND u.id IN ({','.join('?' * len(ids))})",
            ids).fetchall()}
        invalid = [i for i in ids if i not in valid]
        if invalid:
            raise ValidationFailed("Hay usuarios que no son docentes activos",
                                   details={"invalid_user_ids": invalid})
        return "seleccion", None, None, ids, {"mode": "users", "user_ids": ids}
    if mode == "filter":
        campus, unit = rule.get("campus"), rule.get("unit")
        if not campus and not unit:
            raise ValidationFailed("El filtro requiere campus (sede) y/o unit (unidad)")
        sede = unidad = None
        if campus:
            sede = _lookup_mysql(conn, "sede", campus)
            if sede is None:
                raise ValidationFailed("campus no corresponde a una sede",
                                       details={"field": "campus"})
        if unit:
            unidad = _lookup_mysql(conn, "unidad_academica", unit)
            if unidad is None:
                raise ValidationFailed("unit no corresponde a una unidad académica",
                                       details={"field": "unit"})
            if sede is not None and unidad["sede_id"] != sede["id"]:
                raise ValidationFailed("La unidad no pertenece a esa sede",
                                       details={"fields": ["campus", "unit"]})
        out = {"mode": "filter"}
        if sede is not None:
            out["campus"] = sede["nombre"]
        if unidad is not None:
            out["unit"] = unidad["nombre"]
        if unidad is not None:      # la unidad es más específica que la sede
            return "unidad", None, unidad["id"], [], out
        return "sede", sede["id"], None, [], out
    raise ValidationFailed("mode inválido", details={"valid": ["users", "all", "filter"]})


def _eligible_mysql(conn, alcance, sede_id, unidad_id, user_ids):
    """Misma lógica que sp_publicar_tarea de G1 (solo docentes activos)."""
    if alcance == "seleccion":
        return user_ids
    sql, params = f"SELECT DISTINCT u.id {_TEACHERS_MYSQL}", []
    if alcance == "sede":
        sql += " AND ua.sede_id = ?"
        params.append(sede_id)
    elif alcance == "unidad":
        sql += " AND u.unidad_academica_id = ?"
        params.append(unidad_id)
    return [r["id"] for r in conn.execute(sql + " ORDER BY u.id", params).fetchall()]


def set_recipients(conn, actor, task_id, rule):
    with transaction(conn):
        task = _load_task(conn, task_id)
        if not _can_manage(actor, task):
            raise Forbidden("No eres el coordinador autorizado de esta tarea")
        if task["status"] != "draft":
            raise Conflict("Los destinatarios solo se editan en borrador", code="NOT_DRAFT")
        if _is_mysql(conn):
            alcance, sede_id, unidad_id, user_ids, _norm = _normalize_rule_mysql(conn, rule)
            eligible = _eligible_mysql(conn, alcance, sede_id, unidad_id, user_ids)
            if not eligible:
                raise ValidationFailed("La regla no alcanza a ningún docente elegible")
            set_actor(conn, actor["id"])
            conn.execute(
                "UPDATE tarea SET alcance = ?, rol_destino_id = NULL, sede_destino_id = ?,"
                " unidad_destino_id = ? WHERE id = ?", (alcance, sede_id, unidad_id, task_id))
            conn.execute("DELETE FROM tarea_seleccion WHERE tarea_id = ?", (task_id,))
            for uid in user_ids:
                conn.execute("INSERT INTO tarea_seleccion (tarea_id, tipo, usuario_id)"
                             " VALUES (?, 'usuario', ?)", (task_id, uid))
            return {"task": _out(conn, _load_task(conn, task_id)), "eligible_count": len(eligible)}
        norm = _normalize_rule(conn, rule)
        eligible = resolve_recipients(conn, norm)
        if not eligible:
            raise ValidationFailed("La regla no alcanza a ningún docente elegible")
        conn.execute("UPDATE tasks SET recipient_rule = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(norm), utcnow(), task_id))
        return {"task": _out(conn, _load_task(conn, task_id)), "eligible_count": len(eligible)}


# ------------------------------------------------------------------- publish
def _publish_mysql(conn, actor, task_id):
    """Publica con sp_publicar_tarea de G1 (destinatarios, transiciones iniciales y evento)."""
    with transaction(conn):
        set_actor(conn, actor["id"])        # el trigger trg_tarea_evento usa @actor_id
        task = _load_task(conn, task_id)
        rule = transitions.get_rule(task["flow"], "draft", "publish")
        transitions.authorize(rule, actor, task)
        if task["status"] != "draft":
            raise Conflict("La tarea ya fue publicada o cancelada", code="CONFLICT")
        if task["alcance"] not in ("todos", "sede", "unidad", "seleccion"):
            raise ValidationFailed("Configura los destinatarios antes de publicar")
        _call_proc(conn, "sp_publicar_tarea", (task_id, actor["id"]))
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM tarea_destinatario WHERE tarea_id = ? ORDER BY id",
            (task_id,)).fetchall()]
        return {"task": _out(conn, _load_task(conn, task_id)),
                "assignments_created": len(ids), "assignment_ids": ids}


def publish_task(conn, actor, task_id):
    """Crea una asignación por destinatario. Todo o nada, e idempotente (2.ª vez -> 409)."""
    if _is_mysql(conn):
        return _publish_mysql(conn, actor, task_id)
    with transaction(conn):
        task = _load_task(conn, task_id)
        rule = transitions.get_rule(task["flow"], "draft", "publish")
        transitions.authorize(rule, actor, task)
        if task["status"] != "draft":
            raise Conflict("La tarea ya fue publicada o cancelada", code="CONFLICT")
        if not task["recipient_rule"]:
            raise ValidationFailed("Configura los destinatarios antes de publicar")
        ids = resolve_recipients(conn, json.loads(task["recipient_rule"]))
        if not ids:
            raise ValidationFailed("No hay docentes elegibles para publicar")

        now = utcnow()
        cur = conn.execute(
            "UPDATE tasks SET status = 'published', published_at = ?, updated_at = ?"
            " WHERE id = ? AND status = 'draft'", (now, now, task_id))
        if cur.rowcount != 1:
            raise Conflict("La tarea ya fue publicada", code="CONFLICT")

        created = []
        for user_id in ids:
            aid = conn.execute(
                "INSERT INTO assignments(task_id, assignee_id, status, priority, due_date,"
                " created_at, updated_at) VALUES (?,?, 'assigned', ?,?,?,?)",
                (task_id, user_id, task["priority"], task["due_date"], now, now)).lastrowid
            transitions.record_transition(conn, aid, actor["id"], "publish",
                                          "draft", "assigned", None, now)
            transitions.emit_status_changed(conn, task, aid, user_id, actor["id"],
                                            "publish", "draft", "assigned", None)
            created.append(aid)
        events.emit(conn, "task.published", task_id, None, {
            "task_id": task_id, "task_title": task["title"], "actor_id": actor["id"],
            "assignments_created": len(created), "due_date": task["due_date"]})
        return {"task": _out(conn, _load_task(conn, task_id)),
                "assignments_created": len(created), "assignment_ids": created}


# -------------------------------------------------------------------- cancel
def cancel_task(conn, actor, task_id, reason=None):
    """Cancela un borrador o las asignaciones aún en 'assigned'. Nunca borra historia.

    SUPUESTO: las asignaciones que ya avanzaron (in_progress en adelante) NO se cancelan
    (la matriz solo permite cancelar desde draft/assigned) y se reportan en `skipped`.
    La tarea pasa a 'cancelled' solo si no queda ninguna asignación viva.
    En G1: un borrador se da de baja con eliminado_en (eliminación lógica) y una tarea
    publicada pasa a estado 'cancelled' (el trigger de G1 emite task.cancelled).
    """
    mysql = _is_mysql(conn)
    with transaction(conn):
        if mysql:
            set_actor(conn, actor["id"])
        task = _load_task(conn, task_id)
        transitions.authorize(transitions.get_rule(task["flow"], "draft", "cancel"), actor, task)
        if task["status"] == "cancelled":
            raise Conflict("La tarea ya está cancelada", code="ALREADY_CANCELLED")

        cancelled, skipped = [], []
        if task["status"] == "published":
            if mysql:
                rows = conn.execute(
                    "SELECT id, estado_codigo AS status FROM tarea_destinatario"
                    " WHERE tarea_id = ? ORDER BY id", (task_id,)).fetchall()
            else:
                rows = conn.execute("SELECT id, status FROM assignments WHERE task_id = ?"
                                    " ORDER BY id", (task_id,)).fetchall()
            cancellable = [r["id"] for r in rows if r["status"] == "assigned"]
            skipped = [{"assignment_id": r["id"], "status": r["status"]}
                       for r in rows if r["status"] not in ("assigned", "cancelled")]
            if not cancellable and skipped:
                raise Conflict("Ninguna asignación puede cancelarse en su estado actual",
                               details={"skipped": skipped}, code="NOTHING_TO_CANCEL")
            for aid in cancellable:
                transitions.perform(conn, aid, "cancel", actor, reason)
                cancelled.append(aid)

        if not skipped:
            if mysql:
                if task["status"] == "draft":
                    conn.execute(
                        "UPDATE tarea SET eliminado_en = CURRENT_TIMESTAMP(3), eliminado_por = ?"
                        " WHERE id = ? AND estado_codigo = 'draft' AND eliminado_en IS NULL",
                        (actor["id"], task_id))
                else:
                    conn.execute("UPDATE tarea SET estado_codigo = 'cancelled' WHERE id = ?",
                                 (task_id,))
            else:
                now = utcnow()
                conn.execute("UPDATE tasks SET status = 'cancelled', cancelled_at = ?,"
                             " updated_at = ? WHERE id = ?", (now, now, task_id))
                events.emit(conn, "task.cancelled", task_id, None, {
                    "task_id": task_id, "task_title": task["title"], "actor_id": actor["id"],
                    "reason": reason, "assignments_cancelled": len(cancelled)})
        return {"task": _out(conn, _load_task(conn, task_id)),
                "cancelled_assignments": cancelled, "skipped": skipped}


# ------------------------------------------------------- seguimiento / historial
def list_task_assignments(conn, actor, task_id, status=None, page=1, page_size=20):
    task = _load_task(conn, task_id)
    if not _can_view(actor, task):
        raise Forbidden("No tienes acceso a esta tarea")
    mysql = _is_mysql(conn)
    counts = {s: 0 for s in STATES if s != "draft"}
    if mysql:
        count_rows = conn.execute(
            "SELECT estado_codigo AS status, COUNT(*) AS n FROM tarea_destinatario"
            " WHERE tarea_id = ? GROUP BY estado_codigo", (task_id,))
    else:
        count_rows = conn.execute("SELECT status, COUNT(*) n FROM assignments WHERE task_id = ?"
                                  " GROUP BY status", (task_id,))
    for r in count_rows:
        counts[r["status"]] = r["n"]
    if status and status not in counts:
        raise ValidationFailed("status inválido", details={"valid": list(counts)})
    if mysql:
        where, params = "WHERE td.tarea_id = ?", [task_id]
        if status:
            where += " AND td.estado_codigo = ?"
            params.append(status)
        res = _paged(
            conn, "SELECT td.id, td.tarea_id AS task_id, td.usuario_id AS assignee_id,"
                  " td.estado_codigo AS status, t.prioridad AS priority,"
                  " CAST(DATE(COALESCE(td.fecha_limite, t.fecha_limite)) AS CHAR) AS due_date,"
                  " td.asignado_en AS created_at, td.actualizado_en AS updated_at,"
                  " CONCAT(u.nombres, ' ', u.apellidos) AS assignee_name,"
                  " s.nombre AS campus, ua.nombre AS unit,"
                  " (SELECT MAX(x.creado_en) FROM tarea_transicion x"
                  "   WHERE x.tarea_destinatario_id = td.id) AS last_change_at",
            f"FROM tarea_destinatario td JOIN tarea t ON t.id = td.tarea_id"
            f" JOIN usuario u ON u.id = td.usuario_id"
            f" LEFT JOIN unidad_academica ua ON ua.id = u.unidad_academica_id"
            f" LEFT JOIN sede s ON s.id = ua.sede_id {where}",
            params, "td.id", page, page_size)
    else:
        where, params = "WHERE a.task_id = ?", [task_id]
        if status:
            where += " AND a.status = ?"
            params.append(status)
        res = _paged(
            conn, "SELECT a.*, u.name AS assignee_name, u.campus, u.unit,"
                  " (SELECT MAX(created_at) FROM assignment_transitions x"
                  "  WHERE x.assignment_id = a.id) AS last_change_at",
            f"FROM assignments a JOIN users u ON u.id = a.assignee_id {where}",
            params, "a.id", page, page_size)
    res["summary"] = {"total": sum(counts.values()), "by_status": counts}
    return res


def get_history(conn, actor, assignment_id):
    mysql = _is_mysql(conn)
    if mysql:
        row = conn.execute(
            f"SELECT td.usuario_id AS assignee_id, {_TASK_COLS_MYSQL}"
            f" FROM tarea_destinatario td JOIN tarea t ON t.id = td.tarea_id"
            f" JOIN workflow w ON w.id = t.workflow_id WHERE td.id = ?",
            (assignment_id,)).fetchone()
    else:
        row = conn.execute(
            "SELECT a.assignee_id, t.* FROM assignments a JOIN tasks t ON t.id = a.task_id"
            " WHERE a.id = ?", (assignment_id,)).fetchone()
    if row is None:
        raise NotFound(f"Asignación {assignment_id} no existe")
    if actor["id"] != row["assignee_id"] and not _can_view(actor, row):
        raise Forbidden("No tienes acceso al historial de esta asignación")
    if mysql:
        rows = conn.execute(
            "SELECT h.id, h.tarea_destinatario_id AS assignment_id, h.actor_id,"
            " wd.accion AS action, COALESCE(h.estado_anterior, 'draft') AS from_status,"
            " h.estado_nuevo AS to_status, h.comentario AS comment, h.creado_en AS created_at,"
            " CONCAT(u.nombres, ' ', u.apellidos) AS actor_name"
            " FROM tarea_transicion h JOIN workflow_detalle wd ON wd.id = h.workflow_detalle_id"
            " JOIN usuario u ON u.id = h.actor_id"
            " WHERE h.tarea_destinatario_id = ? ORDER BY h.id", (assignment_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT h.*, u.name AS actor_name FROM assignment_transitions h"
            " JOIN users u ON u.id = h.actor_id WHERE h.assignment_id = ? ORDER BY h.id",
            (assignment_id,)).fetchall()
    return [dict(r) for r in rows]


def inbox(conn, actor, status=None, page=1, page_size=20):
    """Asignaciones del docente. Un borrador nunca aparece (no tiene asignaciones)."""
    if TEACHER not in _roles(actor):
        raise Forbidden("Solo los docentes tienen inbox")
    if _is_mysql(conn):
        where = ("WHERE td.usuario_id = ? AND t.estado_codigo <> 'draft'"
                 " AND t.eliminado_en IS NULL")
        params = [actor["id"]]
        if status:
            where += " AND td.estado_codigo = ?"
            params.append(status)
        return _paged(
            conn, "SELECT td.id, td.tarea_id AS task_id, td.usuario_id AS assignee_id,"
                  " td.estado_codigo AS status, t.prioridad AS priority,"
                  " CAST(DATE(COALESCE(td.fecha_limite, t.fecha_limite)) AS CHAR) AS due_date,"
                  " td.asignado_en AS created_at, td.actualizado_en AS updated_at,"
                  " t.titulo AS title, COALESCE(t.descripcion, '') AS description,"
                  " tt.nombre AS type_name, tt.requiere_archivo AS requires_evidence,"
                  " tt.extensiones AS evidence_type",
            f"FROM tarea_destinatario td JOIN tarea t ON t.id = td.tarea_id"
            f" JOIN workflow w ON w.id = t.workflow_id"
            f" JOIN tipo_tarea tt ON tt.id = w.tipo_tarea_id {where}",
            params, "COALESCE(td.fecha_limite, t.fecha_limite), td.id", page, page_size)
    where, params = "WHERE a.assignee_id = ? AND t.status != 'draft'", [actor["id"]]
    if status:
        where += " AND a.status = ?"
        params.append(status)
    return _paged(
        conn, "SELECT a.*, t.title, t.description, ty.name AS type_name,"
              " ty.requires_evidence, ty.evidence_type",
        f"FROM assignments a JOIN tasks t ON t.id = a.task_id"
        f" JOIN task_types ty ON ty.id = t.type_id {where}",
        params, "a.due_date, a.id", page, page_size)