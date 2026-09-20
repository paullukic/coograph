"""get_minimal_context turns a task description into a file set.

The graph under test is built by the real builder over a real (tiny) source
tree, not from hand-inserted rows. Retro caught a bug once that unit tests
missed precisely because they hand-built the records they then asserted on.

Run:  python -m unittest discover .github/code-graph/tests
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

CODE_GRAPH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_GRAPH))

try:
    import server  # noqa: E402
except SystemExit as exc:  # pragma: no cover - missing mcp package
    raise unittest.SkipTest(f"code-graph server not importable: {exc}") from exc

import builder  # noqa: E402


PROJECT = {
    "src/orders/order_service.py": '''
from src.orders.order_repository import OrderRepository
from src.orders.order_validator import validate_order


class OrderService:
    """Places orders."""

    def __init__(self, repo: OrderRepository) -> None:
        self.repo = repo

    def place_order(self, order):
        validate_order(order)
        return self.repo.insert(order)
''',
    "src/orders/order_repository.py": '''
class OrderRepository:
    def insert(self, order):
        return order
''',
    "src/orders/order_validator.py": '''
def validate_order(order):
    return True
''',
    "src/billing/billing_service.py": '''
from src.orders.order_service import OrderService


def charge(service: OrderService):
    return service
''',
    "src/isolated/lonely.py": '''
def solitary_beacon():
    """Depends on nothing and nothing depends on it."""
    return 1
''',
    "tests/test_order_service.py": '''
from src.orders.order_service import OrderService


def service():
    """A fixture named with a word that also appears in the task."""
    return OrderService(None)


def test_place_order_inserts(service):
    assert service is not None
''',
}


class MinimalContextTests(unittest.TestCase):
    tmp: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="coograph-mc-"))
        for rel, body in PROJECT.items():
            path = cls.tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body.lstrip("\n"), encoding="utf-8")
        builder.build(cls.tmp)

        cls._root, cls._db = server.ROOT, server.DB_PATH
        server.ROOT = cls.tmp
        server.DB_PATH = cls.tmp / ".code-graph" / "graph.db"

    @classmethod
    def tearDownClass(cls) -> None:
        server.ROOT, server.DB_PATH = cls._root, cls._db
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- resolution ---------------------------------------------------------

    def test_symbol_in_task_seeds_its_defining_file(self) -> None:
        result = server.get_minimal_context(
            "Add caching to OrderService.place_order()"
        )
        self.assertEqual(result["files_reason"], "")
        self.assertEqual(
            result["files_to_read"][0], "src/orders/order_service.py",
            "the file defining place_order leads the list",
        )

    def test_forward_dependencies_follow_the_seed(self) -> None:
        files = server.get_minimal_context(
            "Add caching to OrderService.place_order()"
        )["files_to_read"]
        for dep in ("src/orders/order_repository.py",
                    "src/orders/order_validator.py"):
            self.assertIn(dep, files, "what the seed imports must be offered")

    def test_definition_beats_a_test_that_matches_too(self) -> None:
        """'service' exact-matches a fixture in the test file.

        Seeding from the test inverts the result, so a non-test match wins.
        """
        files = server.get_minimal_context(
            "Add caching to OrderService.place_order()"
        )["files_to_read"]
        self.assertNotEqual(
            files[0], "tests/test_order_service.py",
            "a test file must never lead the list when a definition matched",
        )

    def test_a_file_named_in_the_task_seeds_the_walk(self) -> None:
        result = server.get_minimal_context("update order_validator")
        self.assertIn("src/orders/order_validator.py", result["files_to_read"])

    # -- honest empties -----------------------------------------------------

    def test_nothing_matches_says_so(self) -> None:
        result = server.get_minimal_context("refactor the flurbleflonk widget")
        self.assertEqual(result["files_to_read"], [])
        self.assertIn("matched", result["files_reason"])

    def test_no_task_says_so(self) -> None:
        result = server.get_minimal_context()
        self.assertEqual(result["files_to_read"], [])
        self.assertEqual(result["files_reason"], "no task given")

    def test_seed_without_edges_returns_itself_and_a_reason(self) -> None:
        result = server.get_minimal_context("fix solitary_beacon")
        self.assertEqual(result["files_to_read"], ["src/isolated/lonely.py"])
        self.assertIn("no dependency edges", result["files_reason"])

    def test_a_fallback_match_is_disclosed(self) -> None:
        """A task naming something absent must not look like a confident hit.

        The graph holds no OrderController; "order" still matches, and a caller
        that cannot tell that apart from an exact hit will trust the wrong file.
        """
        result = server.get_minimal_context("rename OrderController")
        self.assertTrue(result["files_to_read"], "it still answers")
        self.assertIn("ordercontroller", result["files_reason"])
        self.assertIn("fallback", result["files_reason"])

    def test_an_exact_match_carries_no_warning(self) -> None:
        result = server.get_minimal_context("Add caching to place_order")
        self.assertEqual(result["files_reason"], "")

    # -- budget -------------------------------------------------------------

    def test_never_more_than_six_files(self) -> None:
        for task in ("Add caching to OrderService.place_order()",
                     "order", "service order validate insert charge"):
            with self.subTest(task=task):
                files = server.get_minimal_context(task)["files_to_read"]
                self.assertLessEqual(len(files), 6)

    def test_response_stays_inside_the_documented_budget(self) -> None:
        """~150 tokens. Measured on the serialized payload so it cannot drift."""
        payload = json.dumps(
            server.get_minimal_context("Add caching to OrderService.place_order()")
        )
        self.assertLess(
            len(payload) // 4, 150,
            f"response is ~{len(payload) // 4} tokens: {payload}",
        )

    def test_no_per_file_token_map(self) -> None:
        result = server.get_minimal_context("Add caching to place_order")
        self.assertNotIn("approx_tokens", result)

    # -- compatibility ------------------------------------------------------

    def test_preexisting_keys_survive(self) -> None:
        result = server.get_minimal_context("review PR #42")
        for key in ("stats", "uncommitted_risk", "changed_file_count",
                    "next_tool_suggestions"):
            self.assertIn(key, result)
        self.assertEqual(
            result["next_tool_suggestions"],
            ["detect_changes", "get_review_context", "get_impact_radius"],
            "task keywords still steer the suggestions",
        )
        self.assertIsInstance(result["stats"]["nodes"], int)


class IdentifierTests(unittest.TestCase):
    def test_splits_camel_and_snake_keeping_the_whole(self) -> None:
        idents = server._identifiers("Add caching to OrderService.place_order()")
        self.assertIn("place_order", idents)
        self.assertIn("orderservice", idents)
        self.assertIn("caching", idents)

    def test_longest_first(self) -> None:
        idents = server._identifiers("OrderService.place_order()")
        self.assertLess(
            idents.index("place_order"), idents.index("order"),
            "a specific name must outrank the generic word inside it",
        )

    def test_drops_stopwords_and_short_tokens(self) -> None:
        idents = server._identifiers("add a fix to the file")
        self.assertEqual(idents, [])


if __name__ == "__main__":
    unittest.main()
