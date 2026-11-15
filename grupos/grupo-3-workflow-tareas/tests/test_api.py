"""Pruebas HTTP del router. Requieren fastapi + httpx; si no están instalados se omiten.

El login real es el de G2 (token). En las pruebas se reemplaza la dependencia `current_user`
por una que lee el header de PRUEBA `X-Test-User` (solo vive aquí, no en el código real).
"""
import os
import tempfile
import unittest

try:
    from fastapi import FastAPI, Header
    from fastapi.testclient import TestClient
    from workflow.api import router
    from workflow.auth import current_user
    from workflow.deps import get_conn
    from workflow.errors import Unauthorized
    from workflow.http_errors import register_error_handlers
    HAVE_FASTAPI = True
except ImportError:                                   # pragma: no cover
    HAVE_FASTAPI = False

from workflow.db import connect, init_db
from workflow.seed import seed_base

P = "/api/v1"


def make_client(db_path):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    def conn_override():
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def fake_current_user(x_test_user: int = Header(default=None)):
        if x_test_user is None:
            raise Unauthorized("Falta el token")
        conn = connect(db_path)
        try:
            row = conn.execute("SELECT * FROM users WHERE id = ? AND active = 1",
                               (x_test_user,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise Unauthorized("Usuario inválido")
        return dict(row)

    app.dependency_overrides[get_conn] = conn_override
    app.dependency_overrides[current_user] = fake_current_user
    return TestClient(app)


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx no instalados")
class ApiTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = connect(self.path)
        init_db(conn)
        self.ids = seed_base(conn)
        conn.close()
        self.client = make_client(self.path)

    def tearDown(self):
        os.remove(self.path)

    def h(self, uid):
        return {"X-Test-User": str(uid)}

    def new_task(self, **extra):
        body = {"type_id": self.ids["types"]["update_program"], "title": "Programa",
                "due_date": "2026-10-30", "reviewer_id": self.ids["reviewer"], **extra}
        return self.client.post(f"{P}/tasks", headers=self.h(self.ids["coord"]), json=body)

    def new_task_with_recipients(self, rule=None):
        c, coord = self.client, self.h(self.ids["coord"])
        t = self.new_task()
        self.assertEqual(t.status_code, 201)
        tid = t.json()["id"]
        r = c.post(f"{P}/tasks/{tid}/recipients", headers=coord, json=rule or {"mode": "all"})
        self.assertEqual(r.status_code, 200)
        return tid

    def assert_error(self, resp, status, code=None):
        self.assertEqual(resp.status_code, status, resp.text)
        err = resp.json()["error"]
        self.assertEqual(set(err), {"code", "message", "details"})
        if code:
            self.assertEqual(err["code"], code)
        return err

    # ---------------------------------------------------------------- flujo completo
    def test_full_cycle_with_the_six_action_routes(self):
        c, coord = self.client, self.h(self.ids["coord"])
        tid = self.new_task_with_recipients()
        pub = c.post(f"{P}/tasks/{tid}/publish", headers=coord)       # publicar: /publish
        self.assertEqual(pub.status_code, 200)
        self.assertEqual(pub.json()["assignments_created"], 5)
        self.assert_error(c.post(f"{P}/tasks/{tid}/publish", headers=coord), 409)

        t0, rev = self.ids["teachers"][0], self.ids["reviewer"]
        aid = pub.json()["assignment_ids"][0]
        act = lambda a, uid, body=None: c.post(f"{P}/assignments/{aid}/{a}",
                                               headers=self.h(uid), json=body or {})
        self.assert_error(act("start", self.ids["teachers"][1]), 403)
        self.assert_error(act("approve", t0), 403)
        self.assert_error(act("submit", t0), 409, "INVALID_TRANSITION")
        self.assertEqual(act("start", t0).json()["status"], "in_progress")
        self.assertEqual(act("submit", t0).json()["status"], "submitted")
        self.assertEqual(act("review", rev).json()["status"], "under_review")
        self.assert_error(act("return", rev), 422)                    # falta comentario
        self.assertEqual(act("return", rev, {"comment": "Corrija"}).json()["status"], "returned")
        self.assertEqual(act("resubmit", t0).json()["status"], "submitted")
        act("review", rev)
        self.assertEqual(act("approve", rev).json()["status"], "approved")

        hist = c.get(f"{P}/assignments/{aid}/history", headers=coord).json()["items"]
        self.assertEqual(hist[-1]["to_status"], "approved")
        self.assertEqual(c.get(f"{P}/events", headers=self.h(self.ids["authority"])).status_code, 200)

    def test_each_action_route_exists(self):
        paths = {r.path for r in router.routes}
        for a in ("start", "submit", "resubmit", "review", "return", "approve"):
            self.assertIn(f"{P}/assignments/{{assignment_id}}/{a}", paths)

    # ---------------------------------------------------------------- fallas de QA
    def test_publish_goes_to_publish_not_recipients(self):
        tid = self.new_task_with_recipients()
        coord = self.h(self.ids["coord"])
        # /recipients sin cuerpo no publica: pide el cuerpo (422)...
        self.assert_error(self.client.post(f"{P}/tasks/{tid}/recipients", headers=coord), 422)
        self.assertEqual(self.client.get(f"{P}/tasks/{tid}", headers=coord).json()["status"],
                         "draft")
        # ...y /publish sí publica.
        self.assertEqual(self.client.post(f"{P}/tasks/{tid}/publish", headers=coord).status_code, 200)
        self.assertEqual(self.client.get(f"{P}/tasks/{tid}", headers=coord).json()["status"],
                         "published")

    def test_urgent_priority_is_422_with_field_detail(self):
        err = self.assert_error(self.new_task(priority="urgent"), 422, "VALIDATION_ERROR")
        self.assertIn("priority", err["details"])
        tid = self.new_task().json()["id"]
        patch = self.client.patch(f"{P}/tasks/{tid}", headers=self.h(self.ids["coord"]),
                                  json={"priority": "urgent"})
        err = self.assert_error(patch, 422, "VALIDATION_ERROR")
        self.assertIn("priority", err["details"])

    # ------------------------------------------------------- formato de errores
    def test_error_format_401_403_404_409_422(self):
        c = self.client
        self.assert_error(c.get(f"{P}/tasks"), 401, "UNAUTHORIZED")
        self.assert_error(c.get(f"{P}/tasks", headers=self.h(self.ids["teachers"][0])),
                          403, "FORBIDDEN")
        self.assert_error(c.get(f"{P}/tasks/9999", headers=self.h(self.ids["coord"])),
                          404, "NOT_FOUND")
        self.assert_error(c.post(f"{P}/assignments/9999/start",
                                 headers=self.h(self.ids["teachers"][0])), 404, "NOT_FOUND")
        tid = self.new_task_with_recipients()
        coord = self.h(self.ids["coord"])
        c.post(f"{P}/tasks/{tid}/publish", headers=coord)
        self.assert_error(c.post(f"{P}/tasks/{tid}/publish", headers=coord), 409, "CONFLICT")
        self.assert_error(c.post(f"{P}/tasks", headers=coord, json={"title": "x"}),
                          422, "VALIDATION_ERROR")
        self.assert_error(c.get(f"{P}/ruta-que-no-existe", headers=coord), 404, "NOT_FOUND")

    


    # ------------------------------------------------------- hallazgo #9: paginación del contrato
    def test_tasks_list_uses_contract_pagination(self):
        self.new_task()
        self.new_task()
        r = self.client.get(f"{P}/tasks?page=1&per_page=1", headers=self.h(self.ids["coord"]))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(set(body), {"page", "per_page", "total", "data"})
        self.assertEqual((body["page"], body["per_page"], body["total"], len(body["data"])),
                         (1, 1, 2, 1))

    # ------------------------------------------------------- hallazgo #15: solo el revisor designado
    def test_only_the_designated_reviewer_can_review_over_http(self):
        c, coord = self.client, self.h(self.ids["coord"])
        tid = self.new_task_with_recipients()
        pub = c.post(f"{P}/tasks/{tid}/publish", headers=coord).json()
        aid, t0 = pub["assignment_ids"][0], self.ids["teachers"][0]
        for a in ("start", "submit"):
            c.post(f"{P}/assignments/{aid}/{a}", headers=self.h(t0), json={})
        other = self.ids.get("reviewer2")
        if other is not None:
            self.assert_error(c.post(f"{P}/assignments/{aid}/review", headers=self.h(other),
                                     json={}), 403, "FORBIDDEN")
        ok = c.post(f"{P}/assignments/{aid}/review", headers=self.h(self.ids["reviewer"]), json={})
        self.assertEqual(ok.json()["status"], "under_review")


if __name__ == "__main__":
    unittest.main()