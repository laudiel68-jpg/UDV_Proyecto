"""Pruebas del motor de workflow (solo librería estándar: python -m unittest)."""
import sqlite3
import unittest
from unittest.mock import patch

from workflow import events, tasks, transitions
from workflow.db import connect, init_db
from workflow.errors import Conflict, Forbidden, NotFound, ValidationFailed
from workflow.matrix import ACTIONS, FLOWS, STATES
from workflow.seed import seed, seed_base


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        init_db(self.conn)
        self.ids = seed_base(self.conn)
        self.t = self.ids["teachers"]

    def actor(self, key_or_id):
        uid = self.ids[key_or_id] if isinstance(key_or_id, str) else key_or_id
        return transitions.get_actor(self.conn, uid)

    def make_task(self, type_code="update_program", rule=None, publish=False, **extra):
        data = {"type_id": self.ids["types"][type_code], "title": "Tarea de prueba",
                "due_date": "2026-10-30", "priority": "high",
                "reviewer_id": self.ids["reviewer"], **extra}
        coord = self.actor("coord")
        task = tasks.create_task(self.conn, coord, data)
        tasks.set_recipients(self.conn, coord, task["id"],
                             rule or {"mode": "users", "user_ids": [self.t[0]]})
        if publish:
            tasks.publish_task(self.conn, coord, task["id"])
        return task["id"]

    def assignment_of(self, task_id, teacher=None):
        row = self.conn.execute(
            "SELECT id FROM assignments WHERE task_id = ? AND assignee_id = ?",
            (task_id, teacher or self.t[0])).fetchone()
        return row["id"]

    def snapshot(self):
        return {t: [tuple(r) for r in self.conn.execute(f"SELECT * FROM {t} ORDER BY 1")]
                for t in ("tasks", "assignments", "assignment_transitions", "events")}

    def status(self, aid):
        return self.conn.execute("SELECT status FROM assignments WHERE id = ?",
                                 (aid,)).fetchone()["status"]

    def do(self, aid, action, who, comment=None):
        return transitions.perform(self.conn, aid, action, self.actor(who), comment)


class TransitionTests(Base):
    def test_standard_flow_with_return_and_resubmit(self):
        aid = self.assignment_of(self.make_task(publish=True))
        steps = [("start", self.t[0], None, "in_progress"),
                 ("submit", self.t[0], None, "submitted"),
                 ("review", "reviewer", None, "under_review"),
                 ("return", "reviewer", "Falta bibliografía", "returned"),
                 ("resubmit", self.t[0], None, "submitted"),
                 ("review", "reviewer", None, "under_review"),
                 ("approve", "reviewer", None, "approved"),
                 ("close", "coord", None, "closed")]
        for action, who, comment, expected in steps:
            self.assertEqual(self.do(aid, action, who, comment)["status"], expected)
        hist = tasks.get_history(self.conn, self.actor("coord"), aid)
        self.assertEqual([h["action"] for h in hist],
                         ["publish"] + [s[0] for s in steps])
        for h in hist:
            self.assertTrue(h["actor_id"] and h["created_at"] and h["from_status"] and h["to_status"])
        self.assertEqual(hist[4]["comment"], "Falta bibliografía")

    def test_return_without_comment_is_422_and_changes_nothing(self):
        aid = self.assignment_of(self.make_task(publish=True))
        for a, w in (("start", self.t[0]), ("submit", self.t[0]), ("review", "reviewer")):
            self.do(aid, a, w)
        before = self.snapshot()
        for bad in (None, "", "   "):
            with self.assertRaises(ValidationFailed):
                self.do(aid, "return", "reviewer", bad)
        self.assertEqual(before, self.snapshot())

    def test_every_undefined_combination_is_409_and_touches_nothing(self):
        # Un usuario CON permiso para la acción: el único problema es el estado -> 409.
        # (Si el usuario no tuviera permiso, respondería 403 antes; ver el test siguiente.)
        permitted = {"publish": "coord", "start": self.t[0], "submit": self.t[0],
                     "review": "reviewer", "return": "reviewer", "resubmit": self.t[0],
                     "approve": "authority", "close": "system", "cancel": "coord"}
        self.assertEqual(set(permitted), set(ACTIONS))
        for flow, type_code in (("standard", "update_program"), ("short", "confirm_activity")):
            aid = self.assignment_of(self.make_task(type_code, publish=True))
            for state in STATES:
                if state == "draft":
                    continue
                for action in ACTIONS:
                    if (state, action) in FLOWS[flow]:
                        continue
                    with self.subTest(flow=flow, state=state, action=action):
                        self.conn.execute("UPDATE assignments SET status = ? WHERE id = ?",
                                          (state, aid))
                        before = self.snapshot()
                        with self.assertRaises(Conflict):
                            self.do(aid, action, permitted[action])
                        self.assertEqual(before, self.snapshot())

    def test_forbidden_takes_precedence_over_conflict(self):
        """Sin permiso -> 403 aunque la transición además sea inválida (nunca 409)."""
        aid = self.assignment_of(self.make_task(publish=True))          # estado: assigned
        before = self.snapshot()
        cases = [("approve", self.t[0]),      # docente aprobando (rol no permitido), estado inválido
                 ("approve", "coord"),        # coordinador aprobando
                 ("review", "authority"),     # autoridad revisando
                 ("close", self.t[0]),        # docente cerrando
                 ("submit", self.t[1]),       # docente que NO es el destinatario, estado inválido
                 ("review", "reviewer2")]     # revisor que NO es el designado, estado inválido
        for action, who in cases:
            with self.subTest(state="assigned", action=action, who=who):
                with self.assertRaises(Forbidden):
                    self.do(aid, action, who)
        self.assertEqual(before, self.snapshot())

        self.do(aid, "start", self.t[0])                                # estado: in_progress
        with self.assertRaises(Forbidden):
            self.do(aid, "cancel", "coord2")      # coordinador ajeno: 403, no 409
        with self.assertRaises(Forbidden):
            self.do(aid, "approve", self.t[0])

    def test_authorized_user_with_invalid_state_still_gets_409(self):
        aid = self.assignment_of(self.make_task(publish=True))          # estado: assigned
        before = self.snapshot()
        for action, who in (("submit", self.t[0]),       # destinatario correcto, pero falta start
                            ("review", "reviewer"),      # revisor designado, pero aún no hay entrega
                            ("approve", "authority"),    # autoridad, pero no está en revisión
                            ("close", "coord")):         # coordinador dueño, pero no está aprobada
            with self.subTest(action=action, who=who):
                with self.assertRaises(Conflict):
                    self.do(aid, action, who)
        self.assertEqual(before, self.snapshot())

    def test_action_missing_from_flow_is_409_for_everyone(self):
        # En el flujo corto no existen start/review/return/resubmit: no hay permisos que evaluar.
        aid = self.assignment_of(self.make_task("confirm_activity", publish=True))
        for action in ("start", "review", "return", "resubmit"):
            for who in (self.t[0], "authority"):
                with self.subTest(action=action, who=who):
                    with self.assertRaises(Conflict):
                        self.do(aid, action, who)

    def test_unknown_assignment_is_404_before_permissions(self):
        with self.assertRaises(NotFound):
            self.do(9999, "approve", self.t[0])

    def test_non_assignee_cannot_start_or_submit_403(self):
        aid = self.assignment_of(self.make_task(publish=True))
        before = self.snapshot()
        with self.assertRaises(Forbidden):
            self.do(aid, "start", self.t[1])
        self.assertEqual(before, self.snapshot())
        self.do(aid, "start", self.t[0])
        with self.assertRaises(Forbidden):
            self.do(aid, "submit", self.t[1])

    def test_wrong_role_is_403(self):
        aid = self.assignment_of(self.make_task(publish=True))
        with self.assertRaises(Forbidden):
            self.do(aid, "start", "reviewer")
        for a, w in (("start", self.t[0]), ("submit", self.t[0]), ("review", "reviewer")):
            self.do(aid, a, w)
        with self.assertRaises(Forbidden):
            self.do(aid, "approve", self.t[0])
        with self.assertRaises(Forbidden):
            self.do(aid, "approve", "coord")

    def test_only_designated_reviewer_but_authority_can_approve(self):
        aid = self.assignment_of(self.make_task(publish=True))
        for a, w in (("start", self.t[0]), ("submit", self.t[0])):
            self.do(aid, a, w)
        with self.assertRaises(Forbidden):
            self.do(aid, "review", "reviewer2")
        self.do(aid, "review", "reviewer")
        with self.assertRaises(Forbidden):
            self.do(aid, "approve", "reviewer2")
        self.assertEqual(self.do(aid, "approve", "authority")["status"], "approved")
        self.assertEqual(self.do(aid, "close", "system")["status"], "closed")

    def test_cancel_assigned_keeps_history(self):
        aid = self.assignment_of(self.make_task(publish=True))
        with self.assertRaises(Forbidden):
            self.do(aid, "cancel", "coord2")           # coordinador ajeno
        self.do(aid, "cancel", "coord", "Ya no aplica")
        hist = tasks.get_history(self.conn, self.actor("coord"), aid)
        self.assertEqual([h["action"] for h in hist], ["publish", "cancel"])
        self.assertEqual(self.status(aid), "cancelled")

    def test_cancel_in_progress_is_409(self):
        aid = self.assignment_of(self.make_task(publish=True))
        self.do(aid, "start", self.t[0])
        with self.assertRaises(Conflict):
            self.do(aid, "cancel", "coord")

    def test_history_is_immutable(self):
        aid = self.assignment_of(self.make_task(publish=True))
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE assignment_transitions SET comment='x'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("DELETE FROM assignment_transitions WHERE assignment_id = ?", (aid,))

    def test_events_available_for_every_transition(self):
        aid = self.assignment_of(self.make_task(publish=True))
        self.do(aid, "start", self.t[0])
        evs = [e for e in events.list_events(self.conn) if e["assignment_id"] == aid]
        self.assertEqual([e["payload"]["to_status"] for e in evs], ["assigned", "in_progress"])
        self.assertEqual(evs[1]["payload"]["recipient_id"], self.t[0])
        self.assertEqual(evs[1]["payload"]["actor_id"], self.t[0])
        later = events.list_events(self.conn, after_id=evs[0]["id"])      # lectura incremental
        self.assertIn(evs[1]["id"], [e["id"] for e in later])
        self.assertNotIn(evs[0]["id"], [e["id"] for e in later])
        self.assertIn("task.published", [e["event_type"] for e in events.list_events(self.conn)])

    def test_short_flow_skips_start_and_review(self):
        aid = self.assignment_of(self.make_task("confirm_activity", publish=True))
        self.assertEqual(self.do(aid, "submit", self.t[0])["status"], "submitted")
        self.assertEqual(self.do(aid, "approve", "reviewer")["status"], "approved")
        with self.assertRaises(Conflict):
            self.do(aid, "start", self.t[0])

    def test_unknown_assignment_404_and_unknown_action_422(self):
        with self.assertRaises(NotFound):
            self.do(9999, "start", self.t[0])
        aid = self.assignment_of(self.make_task(publish=True))
        with self.assertRaises(ValidationFailed):
            self.do(aid, "explode", self.t[0])

    # ------------------------------------------------ hallazgos #14 y #15
    def test_reviewer_cannot_act_on_a_task_without_designated_reviewer(self):
        """Hallazgo #15: sin revisor_id ningún revisor puede revisar; la autoridad sí aprueba."""
        aid = self.assignment_of(self.make_task(reviewer_id=None, publish=True))
        for a in ("start", "submit"):
            self.do(aid, a, self.t[0])
        before = self.snapshot()
        for who in ("reviewer", "reviewer2"):
            with self.subTest(who=who), self.assertRaises(Forbidden):
                self.do(aid, "review", who)
        self.assertEqual(before, self.snapshot())

    def test_return_and_approve_are_restricted_to_the_designated_reviewer(self):
        aid = self.assignment_of(self.make_task(publish=True))
        for a, w in (("start", self.t[0]), ("submit", self.t[0]), ("review", "reviewer")):
            self.do(aid, a, w)
        before = self.snapshot()
        for action, comment in (("return", "Falta algo"), ("approve", None)):
            with self.subTest(action=action), self.assertRaises(Forbidden):
                self.do(aid, action, "reviewer2", comment)
        self.assertEqual(before, self.snapshot())

    def test_error_codes_are_uppercase(self):
        """Hallazgo #14: los códigos del contrato van en MAYÚSCULAS."""
        aid = self.assignment_of(self.make_task(publish=True))
        with self.assertRaises(Conflict) as cm:
            self.do(aid, "approve", "authority")           # autorizada, pero estado inválido
        self.assertEqual(cm.exception.code, "INVALID_TRANSITION")


class TaskAndPublishTests(Base):
    def test_publish_all_creates_one_assignment_per_eligible_teacher(self):
        tid = self.make_task(rule={"mode": "all"}, publish=True)
        rows = self.conn.execute("SELECT assignee_id FROM assignments WHERE task_id = ?",
                                 (tid,)).fetchall()
        self.assertEqual(sorted(r[0] for r in rows), sorted(self.t))     # 5, sin la docente de baja
        self.assertNotIn(self.ids["inactive_teacher"], [r[0] for r in rows])

    def test_individual_and_filters(self):
        self.assertEqual(self.count_for({"mode": "users", "user_ids": [self.t[2]]}), 1)
        self.assertEqual(self.count_for({"mode": "filter", "campus": "Norte"}), 2)
        self.assertEqual(self.count_for({"mode": "filter", "unit": "Humanidades"}), 2)
        self.assertEqual(self.count_for({"mode": "filter", "campus": "Central",
                                         "unit": "Ingeniería"}), 2)

    def count_for(self, rule):
        tid = self.make_task(rule=rule, publish=True)
        return self.conn.execute("SELECT COUNT(*) FROM assignments WHERE task_id = ?",
                                 (tid,)).fetchone()[0]

    def test_publish_copies_due_date_and_priority(self):
        tid = self.make_task(rule={"mode": "all"}, publish=True, due_date="2026-12-24",
                             priority="low")
        for r in self.conn.execute("SELECT * FROM assignments WHERE task_id = ?", (tid,)):
            self.assertEqual((r["due_date"], r["priority"]), ("2026-12-24", "low"))

    def test_publish_twice_is_409_and_does_not_duplicate(self):
        tid = self.make_task(rule={"mode": "all"}, publish=True)
        before = self.snapshot()
        with self.assertRaises(Conflict):
            tasks.publish_task(self.conn, self.actor("coord"), tid)
        self.assertEqual(before, self.snapshot())

    def test_publish_is_atomic(self):
        tid = self.make_task(rule={"mode": "all"})
        real, calls = events.emit, {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("fallo simulado a mitad de la publicación")
            return real(*a, **k)

        before = self.snapshot()
        with patch.object(events, "emit", flaky):
            with self.assertRaises(RuntimeError):
                tasks.publish_task(self.conn, self.actor("coord"), tid)
        self.assertEqual(before, self.snapshot())          # ninguna asignación, ningún evento
        self.assertEqual(tasks.get_task(self.conn, self.actor("coord"), tid)["status"], "draft")
        tasks.publish_task(self.conn, self.actor("coord"), tid)    # y se puede reintentar

    def test_publish_permissions_and_preconditions(self):
        tid = self.make_task()
        for who in ("coord2", "reviewer", self.t[0]):
            with self.assertRaises(Forbidden):
                tasks.publish_task(self.conn, self.actor(who), tid)
        no_rule = tasks.create_task(self.conn, self.actor("coord"), {
            "type_id": self.ids["types"]["upload_cv"], "title": "x", "due_date": "2026-11-01"})
        with self.assertRaises(ValidationFailed):
            tasks.publish_task(self.conn, self.actor("coord"), no_rule["id"])

    def test_draft_never_in_inbox_published_is(self):
        tid = self.make_task()
        t0 = self.actor(self.t[0])
        self.assertEqual(tasks.inbox(self.conn, t0)["total"], 0)
        tasks.publish_task(self.conn, self.actor("coord"), tid)
        inbox = tasks.inbox(self.conn, t0)
        self.assertEqual(inbox["total"], 1)
        self.assertEqual(inbox["data"][0]["status"], "assigned")

    def test_edit_only_while_draft(self):
        tid = self.make_task()
        coord = self.actor("coord")
        self.assertEqual(tasks.update_task(self.conn, coord, tid, {"title": "Nuevo"})["title"], "Nuevo")
        with self.assertRaises(Forbidden):
            tasks.update_task(self.conn, self.actor("coord2"), tid, {"title": "Hack"})
        tasks.publish_task(self.conn, coord, tid)
        with self.assertRaises(Conflict):
            tasks.update_task(self.conn, coord, tid, {"title": "Tarde"})
        with self.assertRaises(Conflict):
            tasks.set_recipients(self.conn, coord, tid, {"mode": "all"})

    def test_validation_errors_422(self):
        coord = self.actor("coord")
        good = {"type_id": self.ids["types"]["upload_cv"], "title": "t", "due_date": "2026-11-01"}
        for patch_ in ({"priority": "urgent"}, {"due_date": "30/10/2026"}, {"title": " "},
                       {"type_id": 999}, {"reviewer_id": self.t[0]}, {"bogus": 1}):
            with self.subTest(patch_=patch_), self.assertRaises(ValidationFailed):
                tasks.create_task(self.conn, coord, {**good, **patch_})
        tid = self.make_task()
        for rule in ({"mode": "nope"}, {"mode": "users", "user_ids": []},
                     {"mode": "users", "user_ids": [self.ids["inactive_teacher"]]},
                     {"mode": "filter"}, {"mode": "filter", "campus": "Luna"}):
            with self.subTest(rule=rule), self.assertRaises(ValidationFailed):
                tasks.set_recipients(self.conn, coord, tid, rule)
        with self.assertRaises(ValidationFailed):
            tasks.list_task_types(self.conn, page=0)

    def test_only_coordinator_creates_tasks_and_types(self):
        data = {"type_id": self.ids["types"]["upload_cv"], "title": "t", "due_date": "2026-11-01"}
        with self.assertRaises(Forbidden):
            tasks.create_task(self.conn, self.actor(self.t[0]), data)
        with self.assertRaises(Forbidden):
            tasks.create_task_type(self.conn, self.actor(self.t[0]), {"code": "x", "name": "X"})
        created = tasks.create_task_type(self.conn, self.actor("coord"),
                                         {"code": "x", "name": "X", "flow": "short"})
        self.assertEqual(created["flow"], "short")
        with self.assertRaises(Conflict):
            tasks.create_task_type(self.conn, self.actor("coord"), {"code": "x", "name": "Y"})

    def test_cancel_draft(self):
        tid = self.make_task()
        res = tasks.cancel_task(self.conn, self.actor("coord"), tid)
        self.assertEqual(res["task"]["status"], "cancelled")
        with self.assertRaises(Conflict):
            tasks.cancel_task(self.conn, self.actor("coord"), tid)

    def test_cancel_published_all_assigned_keeps_history(self):
        tid = self.make_task(rule={"mode": "all"}, publish=True)
        res = tasks.cancel_task(self.conn, self.actor("coord"), tid, "Se pospone")
        self.assertEqual(len(res["cancelled_assignments"]), 5)
        self.assertEqual(res["task"]["status"], "cancelled")
        for aid in res["cancelled_assignments"]:
            hist = tasks.get_history(self.conn, self.actor("coord"), aid)
            self.assertEqual([h["action"] for h in hist], ["publish", "cancel"])
            self.assertEqual(hist[1]["comment"], "Se pospone")
        types = [e["event_type"] for e in events.list_events(self.conn, limit=1000)]
        self.assertIn("task.cancelled", types)

    def test_cancel_published_with_progress_skips_started_ones(self):
        tid = self.make_task(rule={"mode": "all"}, publish=True)
        self.do(self.assignment_of(tid, self.t[0]), "start", self.t[0])
        res = tasks.cancel_task(self.conn, self.actor("coord"), tid)
        self.assertEqual(len(res["cancelled_assignments"]), 4)
        self.assertEqual(res["skipped"][0]["status"], "in_progress")
        self.assertEqual(res["task"]["status"], "published")

    def test_tracking_individual_and_aggregate(self):
        tid = self.make_task(rule={"mode": "all"}, publish=True)
        self.do(self.assignment_of(tid, self.t[0]), "start", self.t[0])
        self.do(self.assignment_of(tid, self.t[1]), "start", self.t[1])
        self.do(self.assignment_of(tid, self.t[1]), "submit", self.t[1])
        res = tasks.list_task_assignments(self.conn, self.actor("coord"), tid)
        self.assertEqual(res["summary"]["total"], 5)
        by = res["summary"]["by_status"]
        self.assertEqual((by["assigned"], by["in_progress"], by["submitted"]), (3, 1, 1))
        self.assertEqual(len(res["data"]), 5)
        only = tasks.list_task_assignments(self.conn, self.actor("coord"), tid, status="submitted")
        self.assertEqual(only["total"], 1)
        small = tasks.list_task_assignments(self.conn, self.actor("coord"), tid, page_size=2)
        self.assertEqual((len(small["data"]), small["total"]), (2, 5))
        with self.assertRaises(Forbidden):
            tasks.list_task_assignments(self.conn, self.actor("coord2"), tid)

    def test_history_visibility(self):
        aid = self.assignment_of(self.make_task(publish=True))
        self.assertTrue(tasks.get_history(self.conn, self.actor(self.t[0]), aid))
        with self.assertRaises(Forbidden):
            tasks.get_history(self.conn, self.actor(self.t[1]), aid)

    def test_pagination_follows_the_contract(self):
        """Hallazgo #9: page, per_page, total, data."""
        self.make_task(rule={"mode": "all"}, publish=True)
        self.make_task()
        res = tasks.list_tasks(self.conn, self.actor("coord"), page=1, page_size=1)
        self.assertEqual(set(res), {"page", "per_page", "total", "data"})
        self.assertEqual((res["page"], res["per_page"], res["total"], len(res["data"])),
                         (1, 1, 2, 1))


class SeedTests(unittest.TestCase):
    def test_seed_scenario(self):
        conn = connect(":memory:")
        init_db(conn)
        ids = seed(conn)
        coord = transitions.get_actor(conn, ids["coord"])
        ind = tasks.list_task_assignments(conn, coord, ids["individual_task"])
        mass = tasks.list_task_assignments(conn, coord, ids["mass_task"])
        self.assertEqual((ind["total"], mass["total"]), (1, 5))
        self.assertEqual(mass["summary"]["by_status"]["submitted"], 1)
        self.assertEqual(tasks.get_task(conn, coord, ids["draft_task"])["status"], "draft")


class ErrorCodeTests(unittest.TestCase):
    """Hallazgo #14: todos los códigos de error del contrato van en MAYÚSCULAS."""

    def test_default_codes_are_uppercase(self):
        from workflow import errors
        classes = [c for c in vars(errors).values()
                   if isinstance(c, type) and issubclass(c, errors.WorkflowError)]
        self.assertGreaterEqual(len(classes), 6)
        for cls in classes:
            with self.subTest(cls=cls.__name__):
                self.assertEqual(cls.code, cls.code.upper())
        self.assertEqual(errors.NotFound("x").to_dict()["error"]["code"], "NOT_FOUND")
        self.assertEqual(errors.ValidationFailed("x").code, "VALIDATION_ERROR")

    def test_custom_code_is_uppercased(self):
        from workflow.errors import Conflict
        self.assertEqual(Conflict("x", code="invalid_transition").code, "INVALID_TRANSITION")


if __name__ == "__main__":
    unittest.main()