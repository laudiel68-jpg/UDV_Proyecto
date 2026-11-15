import asyncio
import json
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException, Request

from g5_programas import auth as g5_auth
from g5_programas.database import get_session
from g5_programas.errors import ApiError, registrar_errores
from g5_programas import repository
from g5_programas.repository import (
    _assignment_origin_id,
    _save_section,
    _validate_evaluations,
    _validate_responsible_teacher,
    list_programs,
)
from g5_programas.router import router


def _asgi_request(app, method, path, *, headers=(), body=b""):
    messages = []
    request_sent = False

    async def receive():
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": list(headers),
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return start["status"], json.loads(response_body) if response_body else None


class ApiContractTests(unittest.TestCase):
    def test_api_error_is_compatible_with_fastapi_handlers(self):
        error = ApiError(409, "CONFLICT", "No se puede continuar.", {"estado": "inválido"})

        self.assertIsInstance(error, HTTPException)
        self.assertEqual(error.status_code, 409)
        self.assertEqual(
            error.detail,
            {
                "code": "CONFLICT",
                "message": "No se puede continuar.",
                "details": {"estado": "inválido"},
            },
        )

    def test_registered_error_handler_returns_common_http_json(self):
        app = FastAPI()
        registrar_errores(app)

        @app.get("/missing")
        def missing():
            raise ApiError(404, "NOT_FOUND", "Programa no encontrado.", {"id": 99})

        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/missing",
            "raw_path": b"/missing",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        asyncio.run(app(scope, receive, send))
        response_start = next(message for message in messages if message["type"] == "http.response.start")
        response_body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )

        self.assertEqual(response_start["status"], 404)
        self.assertEqual(
            json.loads(response_body),
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Programa no encontrado.",
                    "details": {"id": 99},
                }
            },
        )

    def test_program_list_filters_are_applied_to_count_and_data(self):
        session = Mock()
        count_result = Mock()
        count_result.scalar_one.return_value = 1
        rows_result = Mock()
        rows_result.mappings.return_value = []
        session.execute.side_effect = [count_result, rows_result]

        result = list_programs(
            session,
            2,
            10,
            curso_id=7,
            periodo_id=3,
            sede_id=2,
            estado="draft",
            version=4,
            docente_responsable_id=12,
        )

        self.assertEqual(result, {"page": 2, "per_page": 10, "total": 1, "data": []})
        count_call, rows_call = session.execute.call_args_list
        count_sql = str(count_call.args[0])
        rows_sql = str(rows_call.args[0])
        expected_filters = (
            "pc.curso_id = :curso_id",
            "pv.periodo_id = :periodo_id",
            "pc.sede_id = :sede_id",
            "pv.estado_codigo = :estado",
            "pv.numero_version = :version",
            "pv.docente_responsable_id = :docente_responsable_id",
        )
        for expression in expected_filters:
            self.assertIn(expression, count_sql)
            self.assertIn(expression, rows_sql)
        expected_params = {
            "curso_id": 7,
            "periodo_id": 3,
            "sede_id": 2,
            "estado": "draft",
            "version": 4,
            "docente_responsable_id": 12,
        }
        self.assertEqual(count_call.args[1], expected_params)
        self.assertEqual(
            rows_call.args[1],
            {**expected_params, "limit": 10, "offset": 10},
        )

    def test_program_list_filters_are_in_openapi(self):
        app = FastAPI()
        app.include_router(router)

        parameters = app.openapi()["paths"]["/api/v1/course-programs"]["get"]["parameters"]

        self.assertEqual(
            {parameter["name"] for parameter in parameters},
            {"page", "per_page", "curso_id", "periodo_id", "sede_id", "estado", "version"},
        )

    def test_assignment_origin_id_is_optional_and_validated(self):
        self.assertIsNone(_assignment_origin_id({}))
        self.assertEqual(_assignment_origin_id({"tarea_destinatario_origen_id": "17"}), 17)
        for invalid_id in ("abc", 0, -1, 1.5, True):
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaises(ApiError) as caught:
                    _assignment_origin_id({"tarea_destinatario_origen_id": invalid_id})
                self.assertEqual(caught.exception.status, 422)

    def test_authorize_endpoint_accepts_g2_authority_principal_over_http(self):
        app = FastAPI()
        registrar_errores(app)
        app.include_router(router)

        test_users = {
            "authority-token": SimpleNamespace(
                id=6,
                nombres="Alberto",
                apellidos="Director",
                roles=[SimpleNamespace(codigo="authority")],
            ),
            "teacher-token": SimpleNamespace(
                id=3,
                nombres="Diana",
                apellidos="Docente",
                roles=[SimpleNamespace(codigo="teacher")],
            ),
            "auditor-token": SimpleNamespace(
                id=7,
                nombres="Laura",
                apellidos="Auditora",
                roles=[SimpleNamespace(codigo="auditor")],
            ),
        }

        async def g2_user(request: Request):
            authorization = request.headers.get("authorization", "")
            scheme, _, token = authorization.partition(" ")
            user = test_users.get(token) if scheme.lower() == "bearer" else None
            if user is None:
                raise ApiError(401, "UNAUTHENTICATED", "Token de prueba inválido.")
            return user

        def test_session():
            yield Mock()

        app.dependency_overrides[g5_auth.obtener_usuario_actual] = g2_user
        app.dependency_overrides[get_session] = test_session

        with patch(
            "g5_programas.router.repository.transition",
            return_value={"id": 41, "estado": "authorized"},
        ) as transition:
            status, body = _asgi_request(
                app,
                "POST",
                "/api/v1/program-versions/41/authorize",
                headers=[(b"content-type", b"application/json")],
                body=b"{}",
            )
            self.assertEqual(status, 401)

            status, body = _asgi_request(
                app,
                "POST",
                "/api/v1/program-versions/41/authorize",
                headers=[
                    (b"authorization", b"Bearer teacher-token"),
                    (b"content-type", b"application/json"),
                ],
                body=b"{}",
            )
            self.assertEqual(status, 403)
            transition.assert_not_called()

            status, body = _asgi_request(
                app,
                "POST",
                "/api/v1/program-versions/41/authorize",
                headers=[
                    (b"authorization", b"Bearer authority-token"),
                    (b"content-type", b"application/json"),
                ],
                body=b"{}",
            )

        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True, "version": {"id": 41, "estado": "authorized"}})
        transition.assert_called_once()

    def test_g2_auditor_bearer_can_read_but_not_create_programs_over_http(self):
        app = FastAPI()
        registrar_errores(app)
        app.include_router(router)
        auditor = SimpleNamespace(
            id=7,
            nombres="Laura",
            apellidos="Auditora",
            roles=[SimpleNamespace(codigo="auditor")],
        )
        admin = SimpleNamespace(
            id=1,
            nombres="Ana",
            apellidos="Administradora",
            roles=[SimpleNamespace(codigo="admin")],
        )
        users = {"auditor-token": auditor, "admin-token": admin}

        async def g2_user(request: Request):
            authorization = request.headers.get("authorization", "")
            token = authorization.removeprefix("Bearer ")
            user = users.get(token)
            if user is None:
                raise ApiError(401, "UNAUTHENTICATED", "Token de prueba inválido.")
            return user

        def test_session():
            yield Mock()

        app.dependency_overrides[g5_auth.obtener_usuario_actual] = g2_user
        app.dependency_overrides[get_session] = test_session

        with patch(
            "g5_programas.router.repository.list_programs",
            return_value={"page": 1, "per_page": 20, "total": 0, "data": []},
        ) as list_programs_mock, patch(
            "g5_programas.router.repository.create_program",
        ) as create_program_mock:
            status, body = _asgi_request(
                app,
                "GET",
                "/api/v1/course-programs",
                headers=[(b"authorization", b"Bearer auditor-token")],
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["data"], [])
            list_programs_mock.assert_called_once()

            status, body = _asgi_request(
                app,
                "POST",
                "/api/v1/course-programs",
                headers=[
                    (b"authorization", b"Bearer auditor-token"),
                    (b"content-type", b"application/json"),
                ],
                body=json.dumps({
                    "curso_id": 1,
                    "sede_id": 1,
                    "modalidad_id": 1,
                    "periodo_id": 1,
                }).encode(),
            )

        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "FORBIDDEN")
        create_program_mock.assert_not_called()

    def test_author_can_create_and_manager_can_open_versions_over_http(self):
        app = FastAPI()
        registrar_errores(app)
        app.include_router(router)
        teacher = SimpleNamespace(
            id=5,
            nombres="Diego",
            apellidos="Docente",
            roles=[SimpleNamespace(codigo="teacher")],
        )
        admin = SimpleNamespace(
            id=1,
            nombres="Ana",
            apellidos="Administradora",
            roles=[SimpleNamespace(codigo="admin")],
        )
        users = {"teacher-token": teacher, "admin-token": admin}

        async def g2_user(request: Request):
            authorization = request.headers.get("authorization", "")
            token = authorization.removeprefix("Bearer ")
            user = users.get(token)
            if user is None:
                raise ApiError(401, "UNAUTHENTICATED", "Token de prueba inválido.")
            return user

        def test_session():
            yield Mock()

        app.dependency_overrides[g5_auth.obtener_usuario_actual] = g2_user
        app.dependency_overrides[get_session] = test_session

        with patch(
            "g5_programas.router.repository.create_program",
            return_value={"programa": {"id": 8}, "version": {"id": 41}},
        ) as create_program_mock, patch(
            "g5_programas.router.repository.create_version",
            return_value={"id": 42, "numero_version": 2},
        ) as create_version_mock:
            status, body = _asgi_request(
                app,
                "POST",
                "/api/v1/course-programs",
                headers=[
                    (b"authorization", b"Bearer admin-token"),
                    (b"content-type", b"application/json"),
                ],
                body=json.dumps({
                    "curso_id": 1,
                    "sede_id": 1,
                    "modalidad_id": 1,
                    "periodo_id": 1,
                }).encode(),
            )
            self.assertEqual(status, 403)
            create_program_mock.assert_not_called()

            status, body = _asgi_request(
                app,
                "POST",
                "/api/v1/course-programs",
                headers=[
                    (b"authorization", b"Bearer teacher-token"),
                    (b"content-type", b"application/json"),
                ],
                body=json.dumps({
                    "curso_id": 1,
                    "sede_id": 1,
                    "modalidad_id": 1,
                    "periodo_id": 1,
                }).encode(),
            )
            self.assertEqual(status, 201)
            self.assertEqual(body["programa"]["id"], 8)
            create_program_mock.assert_called_once()

            status, body = _asgi_request(
                app,
                "POST",
                "/api/v1/course-programs/8/versions",
                headers=[
                    (b"authorization", b"Bearer admin-token"),
                    (b"content-type", b"application/json"),
                ],
                body=b'{"periodo_id":2}',
            )

        self.assertEqual(status, 201)
        self.assertEqual(body["numero_version"], 2)
        create_version_mock.assert_called_once()

    def test_teacher_program_list_is_filtered_to_assigned_versions(self):
        app = FastAPI()
        registrar_errores(app)
        app.include_router(router)
        users = {
            "teacher-token": SimpleNamespace(
                id=5,
                nombres="Diego",
                apellidos="Docente",
                roles=[SimpleNamespace(codigo="teacher")],
            ),
            "coordinator-token": SimpleNamespace(
                id=6,
                nombres="Coordinación",
                apellidos="",
                roles=[SimpleNamespace(codigo="coordinator")],
            ),
            "reviewer-token": SimpleNamespace(
                id=7,
                nombres="Revisión",
                apellidos="",
                roles=[SimpleNamespace(codigo="reviewer")],
            ),
        }

        async def g2_user(request: Request):
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            return users[token]

        def test_session():
            yield Mock()

        app.dependency_overrides[g5_auth.obtener_usuario_actual] = g2_user
        app.dependency_overrides[get_session] = test_session

        with patch(
            "g5_programas.router.repository.list_programs",
            return_value={"page": 1, "per_page": 20, "total": 0, "data": []},
        ) as list_programs_mock:
            for token in ("teacher-token", "coordinator-token", "reviewer-token"):
                status, _ = _asgi_request(
                    app,
                    "GET",
                    "/api/v1/course-programs",
                    headers=[(b"authorization", f"Bearer {token}".encode())],
                )
                self.assertEqual(status, 200)

        self.assertEqual(
            [
                call.kwargs["docente_responsable_id"]
                for call in list_programs_mock.call_args_list
            ],
            [5, None, None],
        )

    def test_teacher_cannot_submit_another_teachers_version(self):
        teacher = g5_auth.Actor(
            id=5,
            name="Docente",
            roles=frozenset({"teacher"}),
        )
        session = Mock()
        session.begin.return_value = nullcontext()
        version = {
            "id": 41,
            "estado_codigo": "draft",
            "docente_responsable_id": 8,
        }

        with patch("g5_programas.repository.set_database_actor"), patch(
            "g5_programas.repository._require_version",
            return_value=version,
        ), patch("g5_programas.repository._validate_for_submit") as validate:
            with self.assertRaises(ApiError) as caught:
                repository.transition(session, teacher, 41, "submit")

        self.assertEqual(caught.exception.status, 403)
        validate.assert_not_called()

    def test_coordinator_can_perform_review_transitions_over_http(self):
        app = FastAPI()
        registrar_errores(app)
        app.include_router(router)
        coordinator = SimpleNamespace(
            id=6,
            nombres="Coordinación",
            apellidos="",
            roles=[SimpleNamespace(codigo="coordinator")],
        )

        async def g2_user(request: Request):
            if request.headers.get("authorization") != "Bearer coordinator-token":
                raise ApiError(401, "UNAUTHENTICATED", "Token de prueba inválido.")
            return coordinator

        def test_session():
            yield Mock()

        app.dependency_overrides[g5_auth.obtener_usuario_actual] = g2_user
        app.dependency_overrides[get_session] = test_session

        with patch(
            "g5_programas.router.repository.transition",
            return_value={"id": 41},
        ) as transition:
            for action, body in (
                ("review", b"{}"),
                ("return", b'{"comentario":"Corregir"}'),
                ("approve", b"{}"),
            ):
                status, _ = _asgi_request(
                    app,
                    "POST",
                    f"/api/v1/program-versions/41/{action}",
                    headers=[
                        (b"authorization", b"Bearer coordinator-token"),
                        (b"content-type", b"application/json"),
                    ],
                    body=body,
                )
                self.assertEqual(status, 200)

        self.assertEqual(
            [call.args[3] for call in transition.call_args_list],
            ["review", "return", "approve"],
        )

    def test_teacher_can_only_be_assigned_to_their_own_program_version(self):
        teacher = g5_auth.Actor(
            id=5,
            name="Docente",
            roles=frozenset({"teacher"}),
        )
        repository._require_teacher_is_responsible(teacher, 5)

        with self.assertRaises(ApiError) as caught:
            repository._require_teacher_is_responsible(teacher, 8)
        self.assertEqual(caught.exception.status, 403)

    def test_version_editing_is_limited_to_owner_or_program_manager_over_http(self):
        app = FastAPI()
        registrar_errores(app)
        app.include_router(router)
        users = {
            "teacher-one": SimpleNamespace(
                id=1, nombres="Uno", apellidos="Docente",
                roles=[SimpleNamespace(codigo="teacher")],
            ),
            "teacher-two": SimpleNamespace(
                id=2, nombres="Dos", apellidos="Docente",
                roles=[SimpleNamespace(codigo="teacher")],
            ),
            "coordinator": SimpleNamespace(
                id=3, nombres="Coordinador", apellidos="",
                roles=[SimpleNamespace(codigo="coordinator")],
            ),
            "admin": SimpleNamespace(
                id=4, nombres="Ana", apellidos="Administradora",
                roles=[SimpleNamespace(codigo="admin")],
            ),
        }

        async def g2_user(request: Request):
            authorization = request.headers.get("authorization", "")
            token = authorization.removeprefix("Bearer ")
            user = users.get(token)
            if user is None:
                raise ApiError(401, "UNAUTHENTICATED", "Token de prueba inválido.")
            return user

        session = Mock()
        session.begin.return_value = nullcontext()

        def test_session():
            yield session

        app.dependency_overrides[g5_auth.obtener_usuario_actual] = g2_user
        app.dependency_overrides[get_session] = test_session
        version_row = {
            "id": 41,
            "estado_codigo": "draft",
            "docente_responsable_id": 1,
        }

        with patch("g5_programas.repository.set_database_actor"), patch(
            "g5_programas.repository._require_version",
            return_value=version_row,
        ), patch("g5_programas.repository._save_section") as save_section, patch(
            "g5_programas.repository._serialize_version",
            return_value={"id": 41, "estado": "draft"},
        ):
            request_headers = [
                (b"content-type", b"application/json"),
            ]
            body = b'{"contenido":{"texto":"Actualizado"}}'
            status, response = _asgi_request(
                app,
                "PUT",
                "/api/v1/program-versions/41/sections/descripcion",
                headers=request_headers + [(b"authorization", b"Bearer teacher-two")],
                body=body,
            )
            self.assertEqual(status, 403)
            self.assertEqual(response["error"]["code"], "FORBIDDEN")
            save_section.assert_not_called()

            status, response = _asgi_request(
                app,
                "PUT",
                "/api/v1/program-versions/41/sections/responsables",
                headers=request_headers + [(b"authorization", b"Bearer teacher-one")],
                body=b'{"contenido":{"docente_responsable_id":2}}',
            )
            self.assertEqual(status, 403)
            self.assertEqual(response["error"]["code"], "FORBIDDEN")
            save_section.assert_not_called()

            status, response = _asgi_request(
                app,
                "PUT",
                "/api/v1/program-versions/41/sections/descripcion",
                headers=request_headers + [(b"authorization", b"Bearer teacher-one")],
                body=body,
            )
            self.assertEqual(status, 200)
            save_section.assert_called_once()

            save_section.reset_mock()
            status, response = _asgi_request(
                app,
                "PUT",
                "/api/v1/program-versions/41/sections/descripcion",
                headers=request_headers + [(b"authorization", b"Bearer admin")],
                body=body,
            )
            self.assertEqual(status, 200)
            save_section.assert_called_once()

            save_section.reset_mock()
            status, response = _asgi_request(
                app,
                "PUT",
                "/api/v1/program-versions/41/sections/descripcion",
                headers=request_headers + [(b"authorization", b"Bearer coordinator")],
                body=body,
            )
            self.assertEqual(status, 200)
            save_section.assert_called_once()

    def test_openapi_documents_typed_request_bodies_and_evaluation_example(self):
        app = FastAPI()
        app.include_router(router)
        spec = app.openapi()

        def request_schema(path, method):
            schema = spec["paths"][path][method]["requestBody"]["content"][
                "application/json"
            ]["schema"]
            reference = schema.get("$ref")
            if reference is None:
                reference = next(option["$ref"] for option in schema["anyOf"] if "$ref" in option)
            return spec["components"]["schemas"][reference.rsplit("/", 1)[-1]]

        program = request_schema("/api/v1/course-programs", "post")
        self.assertTrue({"curso_id", "sede_id", "modalidad_id", "periodo_id"} <= set(program["required"]))
        self.assertIn("docente_responsable_id", program["properties"])
        version = request_schema("/api/v1/course-programs/{program_id}/versions", "post")
        self.assertIn("periodo_id", version["required"])
        header = request_schema("/api/v1/program-versions/{version_id}", "put")
        self.assertIn("resumen_cambios", header["properties"])
        transition = request_schema("/api/v1/program-versions/{version_id}/authorize", "post")
        self.assertIn("comentario", transition["properties"])

        evaluation = request_schema(
            "/api/v1/program-versions/{version_id}/sections/evaluacion",
            "put",
        )
        content_schema = evaluation["properties"]["contenido"]
        list_variant = next(
            option for option in content_schema["anyOf"] if option.get("type") == "array"
        )
        evaluation_item = list_variant["items"]
        if "$ref" in evaluation_item:
            evaluation_item = spec["components"]["schemas"][
                evaluation_item["$ref"].rsplit("/", 1)[-1]
            ]
        self.assertIn("nombre", evaluation_item["properties"])
        self.assertIn("ponderacion", evaluation_item["properties"])
        self.assertEqual(evaluation_item["required"], ["nombre", "ponderacion"])
        self.assertIn(
            {"nombre": "Parcial 1", "ponderacion": 30, "semana": 5},
            content_schema["examples"][0],
        )
        responsables = request_schema(
            "/api/v1/program-versions/{version_id}/sections/responsables",
            "put",
        )
        responsables_content = responsables["properties"]["contenido"]
        if "$ref" in responsables_content:
            responsables_content = spec["components"]["schemas"][
                responsables_content["$ref"].rsplit("/", 1)[-1]
            ]
        self.assertIn("docente_responsable_id", responsables_content["properties"])

    def test_responsables_display_update_does_not_replace_assigned_teacher(self):
        session = Mock()

        _save_section(
            session,
            41,
            "responsables",
            {"docente": "Docente asignado", "coordinador": "Coordinación"},
            actor_id=3,
            responsible_context={"curso_id": 1, "periodo_id": 2, "sede_id": 1},
        )

        session.execute.assert_not_called()

    def test_responsables_assignment_requires_active_g1_course_assignment(self):
        session = Mock()
        context = {"curso_id": 1, "periodo_id": 2, "sede_id": 1}

        with patch("g5_programas.repository._one", return_value={"usuario_id": 8}) as find_assignment:
            _save_section(
                session,
                41,
                "responsables",
                {"docente_responsable_id": 8},
                actor_id=3,
                responsible_context=context,
            )

        query, params = find_assignment.call_args.args[1:]
        self.assertIn("FROM docente_curso", query)
        self.assertIn("activo = 1", query)
        self.assertEqual(params, {
            "teacher_id": 8,
            "course_id": 1,
            "period_id": 2,
            "campus_id": 1,
        })
        self.assertEqual(
            session.execute.call_args.args[1],
            {"responsible_id": 8, "id": 41},
        )

        with patch("g5_programas.repository._one", return_value=None):
            with self.assertRaises(ApiError) as caught:
                _validate_responsible_teacher(session, 99, 1, 2, 1)
        self.assertEqual(caught.exception.status, 422)
        self.assertIn("docente_responsable_id", caught.exception.details)

    def test_evaluation_list_missing_fields_returns_field_validation_error(self):
        with self.assertRaises(ApiError) as caught:
            _validate_evaluations([{"actividad": "Parcial 1"}])

        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(
            caught.exception.details,
            {
                "evaluacion[0].nombre": "Campo obligatorio.",
                "evaluacion[0].ponderacion": "Campo obligatorio y numérico.",
            },
        )

    def test_invalid_evaluation_list_is_rejected_before_deleting_existing_rows(self):
        session = Mock()
        with self.assertRaises(ApiError) as caught:
            _save_section(session, 41, "evaluacion", [{"actividad": "Parcial 1"}])

        self.assertEqual(caught.exception.status, 422)
        session.execute.assert_not_called()

    def test_program_version_number_increments_across_periods(self):
        session = Mock()
        session.begin.return_value = nullcontext()
        period_result = Mock()
        period_result.scalar_one.return_value = None
        next_number_result = Mock()
        next_number_result.scalar_one.return_value = 5
        insert_result = Mock()
        insert_result.lastrowid = 92
        session.execute.side_effect = [period_result, next_number_result, insert_result]
        actor = g5_auth.Actor(id=3, name="Coordinador", roles=frozenset({"coordinator"}))

        with patch.object(repository, "set_database_actor"), patch.object(
            repository, "_one", return_value={"id": 8}
        ), patch.object(
            repository, "_require_version", return_value={"id": 92}
        ), patch.object(
            repository, "_serialize_version", return_value={"id": 92, "numero_version": 5}
        ), patch.object(
            repository, "_program_row", return_value={"id": 8}
        ):
            result = repository.create_program(
                session,
                actor,
                {
                    "curso_id": 1,
                    "sede_id": 1,
                    "modalidad_id": 1,
                    "periodo_id": 2,
                },
            )

        self.assertEqual(result["version"]["numero_version"], 5)
        insert_sql = str(session.execute.call_args_list[2].args[0])
        self.assertIn("VALUES (:program_id, :number, :period_id, 'draft'", insert_sql)
        self.assertEqual(session.execute.call_args_list[2].args[1]["number"], 5)
        self.assertIsNone(session.execute.call_args_list[2].args[1]["teacher"])

    def test_program_creation_uses_requested_assigned_teacher(self):
        session = Mock()
        session.begin.return_value = nullcontext()
        period_result = Mock()
        period_result.scalar_one.return_value = None
        next_number_result = Mock()
        next_number_result.scalar_one.return_value = 5
        insert_result = Mock()
        insert_result.lastrowid = 92
        session.execute.side_effect = [period_result, next_number_result, insert_result]
        actor = g5_auth.Actor(id=3, name="Coordinador", roles=frozenset({"coordinator"}))

        with patch.object(repository, "set_database_actor"), patch.object(
            repository, "_one", return_value={"id": 8}
        ), patch.object(
            repository,
            "_validate_responsible_teacher",
            return_value=44,
        ) as validate_teacher, patch.object(
            repository, "_require_version", return_value={"id": 92}
        ), patch.object(
            repository, "_serialize_version", return_value={"id": 92, "numero_version": 5}
        ), patch.object(
            repository, "_program_row", return_value={"id": 8}
        ):
            repository.create_program(
                session,
                actor,
                {
                    "curso_id": 1,
                    "sede_id": 1,
                    "modalidad_id": 1,
                    "periodo_id": 2,
                    "docente_responsable_id": 44,
                },
            )

        validate_teacher.assert_called_once_with(session, 44, 1, 2, 1)
        self.assertEqual(session.execute.call_args_list[2].args[1]["teacher"], 44)

    def test_cloned_version_uses_program_wide_number_and_preserves_owner(self):
        session = Mock()
        session.begin.return_value = nullcontext()
        latest_result = Mock()
        latest_result.scalar_one.return_value = 4
        insert_result = Mock()
        insert_result.lastrowid = 92
        session.execute.side_effect = [latest_result, insert_result]
        actor = g5_auth.Actor(id=3, name="Coordinador", roles=frozenset({"coordinator"}))
        source = {
            "id": 80,
            "nombre": "Programa de curso",
            "docente_responsable_id": 1,
        }

        with patch.object(repository, "set_database_actor"), patch.object(
            repository, "_program_row", return_value={"id": 8, "asignatura": "Curso"}
        ), patch.object(
            repository, "_one", return_value=source
        ), patch.object(
            repository, "_load_sections", return_value={}
        ), patch.object(
            repository, "_require_version", return_value={"id": 92}
        ), patch.object(
            repository, "_serialize_version", return_value={"id": 92, "numero_version": 5}
        ):
            result = repository.create_version(
                session,
                actor,
                8,
                {"periodo_id": 2},
            )

        self.assertEqual(result["numero_version"], 5)
        insert_sql = str(session.execute.call_args_list[1].args[0])
        self.assertIn("docente_responsable_id", insert_sql)
        self.assertEqual(session.execute.call_args_list[1].args[1]["number"], 5)
        self.assertEqual(session.execute.call_args_list[1].args[1]["responsible_id"], 1)


if __name__ == "__main__":
    unittest.main()
