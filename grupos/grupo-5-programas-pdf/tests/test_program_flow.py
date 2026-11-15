import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from g5_programas.domain import editable, ensure_single_authorized, next_status
from g5_programas.errors import ApiError
from g5_programas.auth import Actor, require_role


class ProgramFlowTests(unittest.TestCase):
    """Pruebas rápidas para las reglas de estados, edición y permisos."""

    def test_valid_transitions(self):
        """Comprueba que el programa pueda avanzar por el flujo esperado."""
        cases = (
            ("submit", "draft", "submitted"),
            ("submit", "returned", "submitted"),
            ("review", "submitted", "under_review"),
            ("return", "under_review", "returned"),
            ("approve", "under_review", "approved"),
            ("authorize", "approved", "authorized"),
        )
        for action, current, expected in cases:
            with self.subTest(action=action, current=current):
                self.assertEqual(next_status(action, current), expected)

    def test_invalid_transition_conflicts_without_mutating_source(self):
        """Asegura que una transición fuera de orden no cambie el estado."""
        cases = (
            ("review", "draft"),
            ("approve", "submitted"),
            ("return", "approved"),
            ("authorize", "under_review"),
            ("submit", "authorized"),
        )
        for action, current in cases:
            with self.subTest(action=action, current=current):
                original = current
                with self.assertRaises(ApiError) as caught:
                    next_status(action, current)
                self.assertEqual(caught.exception.status, 409)
                self.assertEqual(current, original)

    def test_only_draft_and_returned_versions_are_editable(self):
        """Solo deja editar borradores y versiones devueltas."""
        editable("draft")
        editable("returned")
        for state in ("authorized", "superseded", "submitted", "under_review", "approved"):
            with self.subTest(state=state):
                with self.assertRaises(ApiError) as caught:
                    editable(state)
                self.assertEqual(caught.exception.status, 409)

    def test_only_one_authorized_version_per_course_and_period(self):
        """Permite que haya una sola versión vigente para el curso y período."""
        authorized = [
            {"programa_curso_id": 8, "periodo_id": 3, "estado_codigo": "authorized"},
        ]
        ensure_single_authorized(authorized, 8, 3)

    def test_duplicate_authorized_versions_conflict(self):
        """Marca como conflicto si ya hay dos versiones vigentes."""
        authorized = [
            {"programa_curso_id": 8, "periodo_id": 3, "estado_codigo": "authorized"},
            {"programa_curso_id": 8, "periodo_id": 3, "estado_codigo": "authorized"},
        ]
        with self.assertRaises(ApiError) as caught:
            ensure_single_authorized(authorized, 8, 3)
        self.assertEqual(caught.exception.status, 409)

    def test_roles_are_taken_from_authenticated_principal(self):
        """Usa los códigos de G1 y sus permisos para cada acción."""
        teacher = Actor(id=12, name="Docente", roles=frozenset({"teacher"}))
        require_role(teacher, "author")
        with self.assertRaises(ApiError) as caught:
            require_role(teacher, "reviewer")
        self.assertEqual(caught.exception.status, 403)

        coordinator = Actor(id=13, name="Coordinación", roles=frozenset({"coordinator"}))
        require_role(coordinator, "author")
        require_role(coordinator, "manager")
        require_role(coordinator, "reviewer")
        require_role(coordinator, "coordinator")

        reviewer = Actor(id=14, name="Revisor", roles=frozenset({"reviewer"}))
        require_role(reviewer, "manager")
        require_role(reviewer, "reviewer")
        with self.assertRaises(ApiError) as caught:
            require_role(reviewer, "author")
        self.assertEqual(caught.exception.status, 403)

        admin = Actor(id=1, name="Administradora", roles=frozenset({"admin"}))
        require_role(admin, "manager")
        with self.assertRaises(ApiError) as caught:
            require_role(admin, "author")
        self.assertEqual(caught.exception.status, 403)

        authority = Actor(id=15, name="Dirección", roles=frozenset({"authority"}))
        require_role(authority, "authority")
        for code in ("admin", "coordinator", "teacher", "reviewer", "authority", "auditor"):
            actor = Actor(id=17, name="Lector", roles=frozenset({code}))
            require_role(actor, "reader")

        for alias in (
            "docente",
            "autoridad",
            "decanatura",
            "decano",
            "elaborador",
            "revisor",
            "coordinador-academico",
        ):
            actor = Actor(id=16, name="Alias", roles=frozenset({alias}))
            with self.subTest(alias=alias), self.assertRaises(ApiError) as caught:
                require_role(actor, "reader")
            self.assertEqual(caught.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
