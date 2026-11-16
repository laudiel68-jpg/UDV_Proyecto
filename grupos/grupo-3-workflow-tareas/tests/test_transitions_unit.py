"""Pruebas unitarias de workflow.transitions y workflow.matrix (pytest + SQLite en memoria).

Autocontenido: crea su propia base con init_db() y no depende de conftest.py.
Copiar a tests/test_transitions_unit.py
"""
import pytest

from workflow import transitions
from workflow.db import connect, init_db, utcnow
from workflow.errors import Conflict, Forbidden, NotFound, ValidationFailed
from workflow.matrix import ACTIONS, BY_ACTION, FLOWS, ROLES, SHORT, STANDARD, STATES

# ids de usuarios de prueba
COORD, TEACHER, OTHER_TEACHER, REVIEWER, OTHER_REVIEWER, AUTHORITY, SYSTEM, INACTIVE = range(1, 9)


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    now = utcnow()
    users = [
        (COORD, "Coord", "coordinator", 1),
        (TEACHER, "Docente", "teacher", 1),
        (OTHER_TEACHER, "Otro docente", "teacher", 1),
        (REVIEWER, "Revisor", "reviewer", 1),
        (OTHER_REVIEWER, "Otro revisor", "reviewer", 1),
        (AUTHORITY, "Autoridad", "authority", 1),
        (SYSTEM, "Sistema", "system", 1),
        (INACTIVE, "Inactivo", "teacher", 0),
    ]
    for uid, name, role, active in users:
        c.execute("INSERT INTO users(id, name, role, active) VALUES (?,?,?,?)",
                  (uid, name, role, active))
    c.execute("INSERT INTO task_types(id, code, name, flow, created_at) VALUES (1,'std','Estandar','standard',?)", (now,))
    c.execute("INSERT INTO task_types(id, code, name, flow, created_at) VALUES (2,'short','Corto','short',?)", (now,))
    yield c
    c.close()


@pytest.fixture
def make_assignment(conn):
    counter = {"n": 0}

    def _make(status="assigned", flow="standard", reviewer_id=REVIEWER):
        counter["n"] += 1
        n = counter["n"]
        now = utcnow()
        conn.execute(
            "INSERT INTO tasks(id, type_id, title, priority, due_date, status, created_by,"
            " reviewer_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (n, 1 if flow == "standard" else 2, f"Tarea {n}", "medium", "2026-12-31",
             "published", COORD, reviewer_id, now, now))
        conn.execute(
            "INSERT INTO assignments(id, task_id, assignee_id, status, priority, due_date,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (n, n, TEACHER, status, "medium", "2026-12-31", now, now))
        return n

    return _make


def actor(conn, uid):
    return transitions.get_actor(conn, uid)


def status_of(conn, aid):
    return conn.execute("SELECT status FROM assignments WHERE id = ?", (aid,)).fetchone()["status"]


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def assert_nothing_written(conn, aid, expected_status):
    assert status_of(conn, aid) == expected_status
    assert count(conn, "assignment_transitions") == 0
    assert count(conn, "events") == 0


# ------------------------------------------------------------------ matrix.py
def test_matrix_rules_are_consistent():
    for rule in STANDARD + SHORT:
        assert rule.from_state in STATES and rule.to_state in STATES
        assert rule.action in ACTIONS
        assert rule.roles <= set(ROLES)
        assert rule.unscoped_roles <= rule.roles


def test_matrix_return_is_the_only_rule_requiring_comment():
    assert [r.action for r in STANDARD if r.comment_required] == ["return"]


def test_matrix_short_flow_skips_review_steps():
    assert ("assigned", "submit") in FLOWS["short"]
    assert ("assigned", "start") not in FLOWS["short"]
    assert ("under_review", "return") not in FLOWS["short"]
    assert "start" not in BY_ACTION["short"]


# ------------------------------------------------------------------ camino feliz
def test_full_standard_flow_happy_path(conn, make_assignment):
    aid = make_assignment("assigned")
    steps = [
        (TEACHER, "start", "in_progress", None),
        (TEACHER, "submit", "submitted", None),
        (REVIEWER, "review", "under_review", None),
        (REVIEWER, "return", "returned", "Falta la evidencia"),
        (TEACHER, "resubmit", "submitted", None),
        (REVIEWER, "review", "under_review", None),
        (REVIEWER, "approve", "approved", None),
        (COORD, "close", "closed", None),
    ]
    for uid, action, expected, comment in steps:
        result = transitions.perform(conn, aid, action, actor(conn, uid), comment)
        assert result["status"] == expected
    assert count(conn, "assignment_transitions") == len(steps)
    assert count(conn, "events") == len(steps)


def test_transition_records_history_and_event(conn, make_assignment):
    aid = make_assignment("assigned")
    transitions.perform(conn, aid, "start", actor(conn, TEACHER))
    row = conn.execute("SELECT * FROM assignment_transitions").fetchone()
    assert (row["assignment_id"], row["actor_id"], row["action"]) == (aid, TEACHER, "start")
    assert (row["from_status"], row["to_status"]) == ("assigned", "in_progress")
    ev = conn.execute("SELECT * FROM events").fetchone()
    assert ev["event_type"] == "assignment.status_changed"
    assert ev["assignment_id"] == aid


def test_short_flow_happy_path(conn, make_assignment):
    aid = make_assignment("assigned", flow="short")
    assert transitions.perform(conn, aid, "submit", actor(conn, TEACHER))["status"] == "submitted"
    assert transitions.perform(conn, aid, "approve", actor(conn, REVIEWER))["status"] == "approved"


def test_coordinator_can_cancel_from_assigned(conn, make_assignment):
    aid = make_assignment("assigned")
    result = transitions.perform(conn, aid, "cancel", actor(conn, COORD))
    assert result["status"] == "cancelled"


def test_teacher_cannot_cancel(conn, make_assignment):
    aid = make_assignment("assigned")
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, "cancel", actor(conn, TEACHER))
    assert_nothing_written(conn, aid, "assigned")


def test_comment_is_trimmed(conn, make_assignment):
    aid = make_assignment("under_review")
    transitions.perform(conn, aid, "return", actor(conn, REVIEWER), "  corregir  ")
    assert conn.execute("SELECT comment FROM assignment_transitions").fetchone()["comment"] == "corregir"


# ------------------------------------------------------------------ 404 / acción desconocida / actor
def test_unknown_assignment_is_404(conn):
    with pytest.raises(NotFound):
        transitions.perform(conn, 999, "start", actor(conn, TEACHER))


def test_unknown_action_is_validation_error(conn, make_assignment):
    aid = make_assignment("assigned")
    with pytest.raises(ValidationFailed):
        transitions.perform(conn, aid, "volar", actor(conn, TEACHER))
    assert_nothing_written(conn, aid, "assigned")


def test_get_actor_rejects_inactive_and_missing_users(conn):
    with pytest.raises(Forbidden):
        transitions.get_actor(conn, INACTIVE)
    with pytest.raises(Forbidden):
        transitions.get_actor(conn, 12345)


# ------------------------------------------------------------------ 403 permisos
def test_wrong_role_is_forbidden(conn, make_assignment):
    aid = make_assignment("assigned")
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, "start", actor(conn, REVIEWER))
    assert_nothing_written(conn, aid, "assigned")


def test_teacher_who_is_not_the_assignee_is_forbidden(conn, make_assignment):
    aid = make_assignment("assigned")
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, "start", actor(conn, OTHER_TEACHER))
    assert_nothing_written(conn, aid, "assigned")


def test_reviewer_who_is_not_designated_is_forbidden(conn, make_assignment):
    aid = make_assignment("submitted", reviewer_id=REVIEWER)
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, "review", actor(conn, OTHER_REVIEWER))
    assert_nothing_written(conn, aid, "submitted")


def test_reviewer_cannot_act_when_task_has_no_reviewer(conn, make_assignment):
    """Hallazgo #15: sin revisor_id ningún revisor puede actuar (ya no vale 'cualquiera')."""
    aid = make_assignment("submitted", reviewer_id=None)
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, "review", actor(conn, OTHER_REVIEWER))
    assert_nothing_written(conn, aid, "submitted")


@pytest.mark.parametrize("state,action,comment", [
    ("submitted", "review", None),
    ("under_review", "return", "Falta evidencia"),
    ("under_review", "approve", None),
])
def test_only_the_designated_reviewer_can_review_return_or_approve(
        conn, make_assignment, state, action, comment):
    aid = make_assignment(state, reviewer_id=REVIEWER)
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, action, actor(conn, OTHER_REVIEWER), comment)
    assert_nothing_written(conn, aid, state)
    assert transitions.perform(conn, aid, action, actor(conn, REVIEWER), comment)["status"]


def test_authority_can_still_approve_a_task_without_reviewer(conn, make_assignment):
    aid = make_assignment("under_review", reviewer_id=None)
    assert transitions.perform(conn, aid, "approve", actor(conn, AUTHORITY))["status"] == "approved"


def test_authority_can_approve_without_being_designated_reviewer(conn, make_assignment):
    aid = make_assignment("under_review", reviewer_id=REVIEWER)
    assert transitions.perform(conn, aid, "approve", actor(conn, AUTHORITY))["status"] == "approved"


def test_authority_cannot_review(conn, make_assignment):
    aid = make_assignment("submitted")
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, "review", actor(conn, AUTHORITY))


def test_system_can_close_but_other_teacher_cannot(conn, make_assignment):
    aid = make_assignment("approved")
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, "close", actor(conn, TEACHER))
    assert transitions.perform(conn, aid, "close", actor(conn, SYSTEM))["status"] == "closed"


def test_forbidden_takes_priority_over_invalid_state(conn, make_assignment):
    """Sin permiso + transición inválida => 403, no 409."""
    aid = make_assignment("assigned")           # approve no es válido desde 'assigned'
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, "approve", actor(conn, TEACHER))
    assert_nothing_written(conn, aid, "assigned")


# ------------------------------------------------------------------ 409 transiciones inválidas
@pytest.mark.parametrize("state,action,uid", [
    ("assigned", "approve", REVIEWER),
    ("assigned", "submit", TEACHER),           # en el flujo estándar hay que hacer start primero
    ("in_progress", "start", TEACHER),
    ("submitted", "close", COORD),
    ("returned", "approve", REVIEWER),
    ("closed", "cancel", COORD),
    ("cancelled", "publish", COORD),
    ("approved", "cancel", COORD),
])
def test_invalid_transition_is_conflict(conn, make_assignment, state, action, uid):
    aid = make_assignment(state)
    with pytest.raises(Conflict):
        transitions.perform(conn, aid, action, actor(conn, uid))
    assert_nothing_written(conn, aid, state)


def test_action_missing_from_flow_is_conflict(conn, make_assignment):
    """'start' no existe en el flujo corto: no hay permisos que evaluar, responde 409."""
    aid = make_assignment("assigned", flow="short")
    with pytest.raises(Conflict):
        transitions.perform(conn, aid, "start", actor(conn, TEACHER))
    assert_nothing_written(conn, aid, "assigned")


def test_double_execution_of_same_action_is_conflict(conn, make_assignment):
    aid = make_assignment("assigned")
    transitions.perform(conn, aid, "start", actor(conn, TEACHER))
    with pytest.raises(Conflict):
        transitions.perform(conn, aid, "start", actor(conn, TEACHER))
    assert count(conn, "assignment_transitions") == 1


# ------------------------------------------------------------------ 422 comentario obligatorio
@pytest.mark.parametrize("comment", [None, "", "   ", "\n\t"])
def test_return_without_comment_is_validation_error(conn, make_assignment, comment):
    aid = make_assignment("under_review")
    with pytest.raises(ValidationFailed):
        transitions.perform(conn, aid, "return", actor(conn, REVIEWER), comment)
    assert_nothing_written(conn, aid, "under_review")


def test_forbidden_takes_priority_over_missing_comment(conn, make_assignment):
    aid = make_assignment("under_review", reviewer_id=REVIEWER)
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, "return", actor(conn, OTHER_REVIEWER), None)


def test_comment_is_optional_for_other_actions(conn, make_assignment):
    aid = make_assignment("assigned")
    assert transitions.perform(conn, aid, "start", actor(conn, TEACHER), None)["status"] == "in_progress"


# ------------------------------------------------------------------ concurrencia
class RacingConn:
    """Envuelve la conexión y, justo antes del UPDATE de perform(), simula que otro
    usuario ya cambió el estado de la asignación."""

    def __init__(self, real):
        self._real = real
        self._raced = False

    def __getattr__(self, name):
        return getattr(self._real, name)

    def execute(self, sql, params=()):
        if sql.startswith("UPDATE assignments") and not self._raced:
            self._raced = True
            self._real.execute("UPDATE assignments SET status = 'cancelled'")
        return self._real.execute(sql, params)


def test_concurrent_update_is_conflict_and_writes_nothing(conn, make_assignment):
    aid = make_assignment("assigned")
    with pytest.raises(Conflict):
        transitions.perform(RacingConn(conn), aid, "start", actor(conn, TEACHER))
    assert status_of(conn, aid) == "assigned"       # el rollback deshizo todo
    assert count(conn, "assignment_transitions") == 0
    assert count(conn, "events") == 0


# ------------------------------------------------------------------ historial inmutable
def test_transition_history_is_append_only(conn, make_assignment):
    aid = make_assignment("assigned")
    transitions.perform(conn, aid, "start", actor(conn, TEACHER))
    with pytest.raises(Exception):
        conn.execute("UPDATE assignment_transitions SET comment = 'x'")
    with pytest.raises(Exception):
        conn.execute("DELETE FROM assignment_transitions")


# ------------------------------------------------------------------ varios roles (G1: usuario_rol)
def multi_role_actor(uid, *roles):
    return {"id": uid, "name": "multi", "active": 1, "role": roles[0], "roles": list(roles)}


def test_user_with_teacher_and_reviewer_roles_can_act_as_assignee(conn, make_assignment):
    aid = make_assignment("assigned")
    who = multi_role_actor(TEACHER, "reviewer", "teacher")
    assert transitions.perform(conn, aid, "start", who)["status"] == "in_progress"


def test_user_with_teacher_and_reviewer_roles_can_review(conn, make_assignment):
    aid = make_assignment("submitted", reviewer_id=REVIEWER)
    who = multi_role_actor(REVIEWER, "teacher", "reviewer")
    assert transitions.perform(conn, aid, "review", who)["status"] == "under_review"


def test_multi_role_user_still_needs_the_scope(conn, make_assignment):
    """Tener el rol docente no basta: debe ser el destinatario de ESA asignación."""
    aid = make_assignment("assigned")
    who = multi_role_actor(REVIEWER, "reviewer", "teacher")
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, "start", who)
    assert_nothing_written(conn, aid, "assigned")


# ------------------------------------------------------------------ errores de los triggers de G1
class FakeDbError(Exception):
    pass


@pytest.mark.parametrize("args,expected", [
    ((1644, "ERROR: transicion no permitida por el workflow de la tarea (409)"), Conflict),
    ((1644, "ERROR: una devolucion exige una observacion (422)"), ValidationFailed),
    ((1644, "ERROR: la tarea no existe (404)"), NotFound),
    ((1213, "Deadlock found when trying to get lock"), Conflict),
    ((1205, "Lock wait timeout exceeded"), Conflict),
])
def test_translate_db_error_maps_g1_trigger_messages(args, expected):
    assert isinstance(transitions._translate_db_error(FakeDbError(*args)), expected)


@pytest.mark.parametrize("exc", [ValueError("x"), FakeDbError(1062, "Duplicate entry"),
                                 FakeDbError(1644, "mensaje sin codigo")])
def test_translate_db_error_ignores_other_errors(exc):
    assert transitions._translate_db_error(exc) is None


# ------------------------------------------------------------------ hallazgo #14: códigos en mayúsculas
def test_error_codes_are_uppercase(conn, make_assignment):
    aid = make_assignment("assigned")
    with pytest.raises(Conflict) as exc:
        transitions.perform(conn, aid, "approve", actor(conn, REVIEWER))
    assert exc.value.code == "INVALID_TRANSITION"

    with pytest.raises(Conflict) as exc:
        transitions.perform(RacingConn(conn), aid, "start", actor(conn, TEACHER))
    assert exc.value.code == "CONCURRENT_UPDATE"


def test_every_explicit_error_code_in_the_services_is_uppercase():
    import pathlib, re
    root = pathlib.Path(transitions.__file__).parent
    codes = []
    for name in ("transitions.py", "tasks.py"):
        codes += re.findall(r'code="([^"]+)"', (root / name).read_text(encoding="utf-8"))
    assert codes and all(c == c.upper() for c in codes), codes


# ------------------------------------------------------------------ hallazgo #9: paginación del contrato
def test_list_tasks_uses_the_contract_pagination(conn):
    from workflow import tasks
    for i in range(3):
        tasks.create_task(conn, actor(conn, COORD),
                          {"type_id": 1, "title": f"T{i}", "due_date": "2026-12-31"})
    res = tasks.list_tasks(conn, actor(conn, COORD), page=2, page_size=2)
    assert set(res) == {"page", "per_page", "total", "data"}
    assert (res["page"], res["per_page"], res["total"]) == (2, 2, 3)
    assert len(res["data"]) == 1


def test_per_page_out_of_range_is_validation_error(conn):
    from workflow import tasks
    for bad in (0, 101):
        with pytest.raises(ValidationFailed):
            tasks.list_tasks(conn, actor(conn, COORD), page_size=bad)


# ------------------------------------------------------------------ prioridades dinámicas (PR #27)
def test_priority_is_validated_against_the_g1_catalog_including_urgent():
    from workflow import tasks
    from workflow.db import MySQLConn

    class FakeCursor:
        def fetchall(self):
            return [("low",), ("medium",), ("high",), ("urgent",)]

    class FakeMySQL(MySQLConn):
        def __init__(self):
            self.in_transaction = False

        def execute(self, sql, params=()):
            assert "prioridad_tarea" in sql
            return FakeCursor()

    conn = FakeMySQL()
    tasks._validate_fields(conn, {"priority": "urgent"})          # el catálogo la acepta
    with pytest.raises(ValidationFailed):
        tasks._validate_fields(conn, {"priority": "critica"})     # no está en el catálogo


def test_api_does_not_restrict_priority_to_a_fixed_list():
    """El PR #27 quitó `Priority = Literal[...]`: la prioridad se valida contra el catálogo."""
    import pathlib
    src = (pathlib.Path(transitions.__file__).parent / "api.py").read_text(encoding="utf-8")
    assert "Literal" not in src


# ------------------------------------------------------------------ hallazgo #15 (regla exacta de QA)
# 1) con revisor_id  -> SOLO el revisor designado.
# 2) sin revisor_id  -> SOLO coordinación (dueña de la tarea) o administración.
# 'admin' no existe en el CHECK de SQLite, así que se forja el actor con un id de usuario existente.
REVIEW_STEPS = [
    ("submitted", "review", None),
    ("under_review", "return", "Falta evidencia"),
]


@pytest.mark.parametrize("state,action,comment", REVIEW_STEPS)
def test_with_reviewer_only_designated_reviewer_not_coordinator_nor_admin(
        conn, make_assignment, state, action, comment):
    aid = make_assignment(state, reviewer_id=REVIEWER)
    for who in (actor(conn, COORD),                        # coordinación dueña de la tarea
                multi_role_actor(OTHER_TEACHER, "admin"),  # administración
                actor(conn, OTHER_REVIEWER)):              # otro revisor
        with pytest.raises(Forbidden):
            transitions.perform(conn, aid, action, who, comment)
        assert_nothing_written(conn, aid, state)
    assert transitions.perform(conn, aid, action, actor(conn, REVIEWER), comment)["status"]


@pytest.mark.parametrize("state,action,comment", REVIEW_STEPS)
def test_without_reviewer_coordinator_owner_can(conn, make_assignment, state, action, comment):
    aid = make_assignment(state, reviewer_id=None)
    assert transitions.perform(conn, aid, action, actor(conn, COORD), comment)["status"]


@pytest.mark.parametrize("state,action,comment", REVIEW_STEPS)
def test_without_reviewer_admin_can(conn, make_assignment, state, action, comment):
    aid = make_assignment(state, reviewer_id=None)
    who = multi_role_actor(OTHER_TEACHER, "admin")
    assert transitions.perform(conn, aid, action, who, comment)["status"]


@pytest.mark.parametrize("state,action,comment", REVIEW_STEPS)
def test_without_reviewer_others_are_forbidden(conn, make_assignment, state, action, comment):
    aid = make_assignment(state, reviewer_id=None)
    outsiders = (actor(conn, REVIEWER), actor(conn, OTHER_REVIEWER), actor(conn, TEACHER),
                 actor(conn, AUTHORITY), actor(conn, SYSTEM),
                 multi_role_actor(OTHER_TEACHER, "coordinator"))   # coordinación ajena a la tarea
    for who in outsiders:
        with pytest.raises(Forbidden):
            transitions.perform(conn, aid, action, who, comment)
        assert_nothing_written(conn, aid, state)


def test_approve_rule_is_unchanged(conn, make_assignment):
    aid = make_assignment("under_review", reviewer_id=REVIEWER)
    with pytest.raises(Forbidden):
        transitions.perform(conn, aid, "approve", actor(conn, COORD))
    assert transitions.perform(conn, aid, "approve", actor(conn, AUTHORITY))["status"] == "approved"