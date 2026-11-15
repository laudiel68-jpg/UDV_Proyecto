"""Servicio de transiciones: el ÚNICO lugar que decide si una acción es válida.

Recibe "esta asignación, esta acción, este usuario" y verifica, en orden:
    1. la asignación existe                                  -> 404
    2. el usuario tiene permiso para la acción               -> 403
         (su rol puede ejecutarla y es el destinatario / revisor / coordinador correcto)
    3. el estado actual permite la acción (según el flujo)   -> 409
    4. el comentario obligatorio está presente               -> 422
Los permisos van ANTES que el estado: quien no puede ejecutar una acción recibe 403 aunque la
transición además sea inválida (y no se le revela en qué estado está la asignación).
Todas las verificaciones ocurren ANTES de escribir, así un rechazo no toca la base.

Dos dialectos (se elige según el tipo de conexión):
    * SQLite (tests): tablas propias users / assignments / assignment_transitions / events.
    * MySQL (G1):     usuario(+usuario_rol) / tarea_destinatario / tarea_transicion.
                      Los eventos (submitted / returned / approved) los crea el trigger
                      trg_tt_evento de G1, por eso aquí NO se insertan en MySQL.
"""
import re

from . import events
from .db import MySQLConn, set_actor, transaction, utcnow
from .errors import Conflict, Forbidden, NotFound, ValidationFailed
from .matrix import ACTIONS, ADMIN, BY_ACTION, COORDINATOR, FLOWS


def _is_mysql(conn) -> bool:
    return isinstance(conn, MySQLConn)


# ------------------------------------------------------------------ usuarios y permisos
def get_actor(conn, actor_id):
    """Devuelve el usuario como dict con `id`, `roles` (lista) y `role` (el primero)."""
    if _is_mysql(conn):
        row = conn.execute(
            "SELECT id, nombres, apellidos, activo FROM usuario"
            " WHERE id = ? AND eliminado_en IS NULL", (actor_id,)).fetchone()
        if row is None or not row["activo"]:
            raise Forbidden("Usuario inexistente o inactivo")
        roles = [r["codigo"] for r in conn.execute(
            "SELECT r.codigo FROM usuario_rol ur JOIN rol r ON r.id = ur.rol_id"
            " WHERE ur.usuario_id = ? AND r.activo = 1 ORDER BY r.id", (actor_id,)).fetchall()]
        return {"id": row["id"], "name": f"{row['nombres']} {row['apellidos']}", "active": 1,
                "roles": roles, "role": roles[0] if roles else None}
    row = conn.execute("SELECT * FROM users WHERE id = ?", (actor_id,)).fetchone()
    if row is None or not row["active"]:
        raise Forbidden("Usuario inexistente o inactivo")
    actor = dict(row)
    actor["roles"] = [actor["role"]]
    return actor


def _roles(actor) -> set:
    """Roles del usuario. En G1 una persona puede tener varios (p. ej. revisor y docente)."""
    roles = actor.get("roles")
    return set(roles) if roles else {actor.get("role")}


def get_rule(flow, state, action):
    rule = FLOWS[flow].get((state, action))
    if rule is None:
        raise Conflict(
            f"La acción '{action}' no es válida desde el estado '{state}'",
            details={"state": state, "action": action}, code="INVALID_TRANSITION")
    return rule


def authorize(rule, actor, task, assignee_id=None):
    """Verifica rol y alcance. `task` es un dict/Row con created_by, responsible_id, reviewer_id."""
    roles = _roles(actor)
    if not roles & rule.roles:
        raise Forbidden(f"Los roles {sorted(r for r in roles if r)} no pueden ejecutar '{rule.action}'")
    if rule.scope is None or roles & rule.unscoped_roles:
        return
    if rule.scope == "assignee":
        if actor["id"] != assignee_id:
            raise Forbidden("Solo el docente destinatario puede ejecutar esta acción")
    elif rule.scope == "task_reviewer":
        # Regla de QA (hallazgo #15):
        #   * con revisor_id  -> ÚNICAMENTE el revisor designado (ni coordinación ni admin);
        #   * sin revisor_id  -> solo administración, o la coordinación dueña de la tarea.
        # Los roles exentos (unscoped_roles, p. ej. la autoridad al aprobar) ya salieron arriba.
        if task["reviewer_id"] is not None:
            if task["reviewer_id"] != actor["id"]:
                raise Forbidden("No eres el revisor designado de esta tarea")
        elif ADMIN in roles:
            pass
        elif COORDINATOR in roles and actor["id"] in (task["created_by"], task["responsible_id"]):
            pass
        else:
            raise Forbidden("La tarea no tiene revisor designado: solo coordinación o "
                            "administración puede ejecutar esta acción")
    elif rule.scope == "task_coordinator":
        if actor["id"] not in (task["created_by"], task["responsible_id"]):
            raise Forbidden("No eres el coordinador autorizado de esta tarea")


def authorize_action(flow, action, actor, task, assignee_id=None):
    """Permisos de una acción SIN mirar el estado actual (así se puede responder 403 antes que 409).

    Una acción puede tener varias reglas en el flujo (una por estado de origen). El usuario
    pasa si alguna le da permiso; si ninguna lo hace, se propaga el primer 403.
    Si la acción no existe en el flujo no hay nada que autorizar: lo resuelve get_rule() con 409.
    """
    first_error = None
    for rule in BY_ACTION[flow].get(action, ()):
        try:
            authorize(rule, actor, task, assignee_id)
            return
        except Forbidden as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


# ------------------------------------------------------------------ escritura
def record_transition(conn, assignment_id, actor_id, action, from_state, to_state,
                      comment, now=None):
    """Registra la transición en el historial.

    IMPORTANTE (MySQL): llamar ANTES de cambiar el estado de la asignación. El trigger
    trg_tt_valida de G1 compara `estado_anterior` con el estado ACTUAL de la asignación.
    G1 no guarda `action`: guarda `workflow_detalle_id`, que se busca por origen y destino.
    """
    if _is_mysql(conn):
        wd = conn.execute(
            "SELECT wd.id FROM workflow_detalle wd"
            " JOIN tarea t ON t.workflow_id = wd.workflow_id"
            " JOIN tarea_destinatario td ON td.tarea_id = t.id"
            " WHERE td.id = ? AND wd.estado_origen <=> ? AND wd.estado_destino = ?",
            (assignment_id, from_state, to_state)).fetchone()
        if wd is None:
            raise Conflict(
                f"El workflow de la tarea no define la transición '{from_state}' -> '{to_state}'",
                details={"state": from_state, "action": action}, code="INVALID_TRANSITION")
        conn.execute(
            "INSERT INTO tarea_transicion (tarea_destinatario_id, workflow_detalle_id, actor_id,"
            " estado_anterior, estado_nuevo, comentario) VALUES (?,?,?,?,?,?)",
            (assignment_id, wd["id"], actor_id, from_state, to_state, comment))
        return                                   # creado_en y secuencia los pone MySQL
    conn.execute(
        "INSERT INTO assignment_transitions"
        "(assignment_id, actor_id, action, from_status, to_status, comment, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (assignment_id, actor_id, action, from_state, to_state, comment, now or utcnow()))


def _update_status(conn, assignment_id, new_state, old_state, now):
    """UPDATE con guarda de estado: rowcount 0 significa que otro se adelantó."""
    if _is_mysql(conn):
        return conn.execute(
            "UPDATE tarea_destinatario SET estado_codigo = ? WHERE id = ? AND estado_codigo = ?",
            (new_state, assignment_id, old_state))
    return conn.execute(
        "UPDATE assignments SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
        (new_state, now, assignment_id, old_state))


def emit_status_changed(conn, task, assignment_id, assignee_id, actor_id, action,
                        from_state, to_state, comment):
    if _is_mysql(conn):
        return      # G1 lo hace con el trigger trg_tt_evento (nombres y clave_unica propios)
    events.emit(conn, "assignment.status_changed", task["id"], assignment_id, {
        "assignment_id": assignment_id, "task_id": task["id"], "task_title": task["title"],
        "recipient_id": assignee_id, "actor_id": actor_id, "action": action,
        "from_status": from_state, "to_status": to_state, "comment": comment,
        "due_date": task["due_date"], "reviewer_id": task["reviewer_id"],
    })


# ------------------------------------------------------------------ consultas por dialecto
_SELECT_SQLITE = (
    "SELECT a.*, t.title, t.created_by, t.responsible_id, t.reviewer_id, ty.flow,"
    "       t.id AS tid"
    " FROM assignments a JOIN tasks t ON t.id = a.task_id"
    " JOIN task_types ty ON ty.id = t.type_id WHERE a.id = ?")

# Alias a los nombres del modelo propio para no tocar el resto del código.
# G1 no tiene `flow` ni `responsible_id`: hoy todos sus workflows son el estándar.
_SELECT_MYSQL = (
    "SELECT td.id, td.tarea_id AS task_id, td.usuario_id AS assignee_id,"
    "       td.estado_codigo AS status, COALESCE(td.fecha_limite, t.fecha_limite) AS due_date,"
    "       t.titulo AS title, t.creado_por AS created_by, NULL AS responsible_id,"
    "       COALESCE(td.revisor_id, t.revisor_id) AS reviewer_id,"
    "       'standard' AS flow, t.id AS tid, COALESCE(tt.requiere_archivo, 0) AS requires_file"
    " FROM tarea_destinatario td JOIN tarea t ON t.id = td.tarea_id"
    " LEFT JOIN workflow w ON w.id = t.workflow_id"
    " LEFT JOIN tipo_tarea tt ON tt.id = w.tipo_tarea_id"
    " WHERE td.id = ? AND t.eliminado_en IS NULL")

_RESULT_SQLITE = "SELECT * FROM assignments WHERE id = ?"
_RESULT_MYSQL = (
    "SELECT td.id, td.tarea_id AS task_id, td.usuario_id AS assignee_id,"
    "       td.estado_codigo AS status,"
    "       CAST(DATE(COALESCE(td.fecha_limite, t.fecha_limite)) AS CHAR) AS due_date,"
    "       td.asignado_en AS created_at, td.actualizado_en AS updated_at"
    " FROM tarea_destinatario td JOIN tarea t ON t.id = td.tarea_id WHERE td.id = ?")

_COMMENT_CODE = re.compile(r"\((\d{3})\)\s*$")


def _translate_db_error(exc):
    """Convierte errores de los triggers de G1 (SQLSTATE 45000, mensaje terminado en (409),
    (422) o (404)) y los bloqueos de MySQL en los errores de la API. None = no es uno de ellos."""
    args = getattr(exc, "args", ())
    if len(args) != 2 or not isinstance(args[0], int):
        return None
    errno, msg = args[0], str(args[1])
    if errno in (1205, 1213):                              # lock wait timeout / deadlock
        return Conflict("La asignación está siendo modificada por otra solicitud",
                        code="CONCURRENT_UPDATE")
    if errno == 1644:                                      # SIGNAL SQLSTATE '45000'
        found = _COMMENT_CODE.search(msg)
        code = found.group(1) if found else None
        if code == "409":
            return Conflict(msg, code="DB_CONFLICT")
        if code == "422":
            return ValidationFailed(msg, details={"source": "database"})
        if code == "404":
            return NotFound(msg)
    return None


# ------------------------------------------------------------------ operación principal


ENTREGA_ACTIONS = ('submit', 'resubmit')

def _current_entrega(conn, assignment_id):
    """Id del intento actual: la última fila de `entrega` de la asignación que NO tiene una
    transición 'submitted' posterior en tarea_transicion; None si no hay. Regla común de G3 y G4
    (decisión del PM, 13-nov-2026). Hay que llamarla ANTES de registrar la transición de este
    envío, porque esa misma transición cerraría el intento."""
    row = conn.execute(
        "SELECT e.id FROM entrega e WHERE e.tarea_destinatario_id = ?"
        " AND NOT EXISTS (SELECT 1 FROM tarea_transicion tt"
        "   WHERE tt.tarea_destinatario_id = e.tarea_destinatario_id"
        "   AND tt.estado_nuevo = 'submitted' AND tt.creado_en >= e.entregado_en)"
        " ORDER BY e.numero_intento DESC LIMIT 1", (assignment_id,)).fetchone()
    return row["id"] if row else None


def _entrega_has_files(conn, entrega_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM archivo WHERE entrega_id = ? AND eliminado_en IS NULL LIMIT 1",
        (entrega_id,)).fetchone() is not None


def _create_entrega(conn, assignment_id, actor_id):
    """Crea la fila de `entrega` del intento (numero_intento = MAX + 1) con el texto del
    borrador. Solo se llama si no existe un intento actual (G4 ya lo crea al vincular archivos)."""
    conn.execute(
        "INSERT INTO entrega (tarea_destinatario_id, numero_intento, entregado_por,"
        " contenido_texto, programa_version_id)"
        " SELECT ?, COALESCE(MAX(numero_intento), 0) + 1, ?,"
        "  (SELECT contenido_texto FROM entrega_borrador WHERE tarea_destinatario_id = ?),"
        "  (SELECT programa_version_id FROM entrega_borrador WHERE tarea_destinatario_id = ?)"
        " FROM entrega WHERE tarea_destinatario_id = ?",
        (assignment_id, actor_id, assignment_id, assignment_id, assignment_id))


def perform(conn, assignment_id, action, actor, comment=None):
    """Ejecuta una acción sobre una asignación. Devuelve la asignación actualizada."""
    if action not in ACTIONS:
        raise ValidationFailed(f"Acción desconocida: '{action}'", details={"valid": list(ACTIONS)})
    comment = (comment or "").strip() or None
    mysql = _is_mysql(conn)

    with transaction(conn):
        set_actor(conn, actor["id"])           # auditoría de G1 (@actor_id); no-op en SQLite
        row = conn.execute(_SELECT_MYSQL if mysql else _SELECT_SQLITE, (assignment_id,)).fetchone()
        if row is None:
            raise NotFound(f"Asignación {assignment_id} no existe")

        authorize_action(row["flow"], action, actor, row, row["assignee_id"])   # 403 (primero)
        rule = get_rule(row["flow"], row["status"], action)                     # 409
        authorize(rule, actor, row, row["assignee_id"])   # 403 (la regla exacta; defensivo)
        if rule.comment_required and not comment:                               # 422
            raise ValidationFailed(f"La acción '{action}' requiere un comentario",
                                   details={"field": "comment"})

        entrega_id = None
        if mysql and action in ENTREGA_ACTIONS:
            entrega_id = _current_entrega(conn, assignment_id)
            if row["requires_file"] and (
                entrega_id is None or not _entrega_has_files(conn, entrega_id)
            ):
                raise ValidationFailed(
                    "Este tipo de tarea requiere adjuntar un archivo para entregar",
                    details={"field": "file"}
                )

        now = utcnow()
        try:
            # Primero el historial (el trigger de G1 mira el estado actual) y luego el UPDATE
            # con guarda; si otro se adelantó, rowcount != 1 y el rollback deshace el INSERT.
            record_transition(conn, assignment_id, actor["id"], action, row["status"],
                              rule.to_state, comment, now)
            cur = _update_status(conn, assignment_id, rule.to_state, row["status"], now)
            if cur.rowcount != 1:                                      # carrera concurrente
                raise Conflict("La asignación cambió de estado mientras se procesaba",
                               code="CONCURRENT_UPDATE")
            if mysql and action in ENTREGA_ACTIONS and entrega_id is None:
                _create_entrega(conn, assignment_id, actor["id"])
        except Exception as exc:
            mapped = _translate_db_error(exc)
            if mapped is None:
                raise
            raise mapped from exc

        task = {"id": row["tid"], "title": row["title"], "due_date": row["due_date"],
                "reviewer_id": row["reviewer_id"]}
        emit_status_changed(conn, task, assignment_id, row["assignee_id"], actor["id"],
                            action, row["status"], rule.to_state, comment)

        return dict(conn.execute(_RESULT_MYSQL if mysql else _RESULT_SQLITE,
                                 (assignment_id,)).fetchone())