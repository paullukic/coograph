"""Python `calls` edges through modules and objects.

Built by the real builder over a real (tiny) multi-repo tree, the same way
test_minimal_context.py does it. One test per scenario in
openspec/changes/2026-10-23-python-attribute-calls/specs/code-graph/spec.md.

Run:  python -m unittest discover .github/code-graph/tests
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

CODE_GRAPH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_GRAPH))

import builder  # noqa: E402

try:
    import server  # noqa: E402
except SystemExit as exc:  # pragma: no cover - missing mcp package
    raise unittest.SkipTest(f"code-graph server not importable: {exc}") from exc
from parsers.tree_sitter import core  # noqa: E402

if not core.AVAILABLE or core.get_lang(".py") is None:  # pragma: no cover
    raise unittest.SkipTest("tree-sitter-python not installed")


PROJECT = {
    "repo1/app/services/ios/iap_service.py": '''
def verify_receipt(product_id, receipt):
    return True
''',
    "repo1/app/endpoints/premium.py": '''
from services.ios import iap_service
from services.ios import iap_service as iap


def buy(x):
    return iap_service.verify_receipt(x, x)


def restore(x):
    return iap.verify_receipt(x, x)


def checkout(db, User):
    return db.query(User).filter(User.id == 1).first()


def commit_it(session):
    session.commit()


def process_it(obj):
    obj.process()
''',
    "repo1/app/x/util.py": '''
def go():
    return 1
''',
    "repo1/app/main.py": '''
from x import util


def start():
    return util.go()


def rescore(policy):
    return policy.recalculate_score()


def local():
    return helper()


def helper():
    return 2
''',
    "repo1/app/models/policy.py": '''
class Policy:
    def recalculate_score(self):
        return self.normalise()

    def normalise(self):
        return 0

    def commit(self):
        return None
''',
    "repo1/app/workers/a.py": '''
def process():
    return 1
''',
    "repo1/app/workers/b.py": '''
def process():
    return 2
''',
    "repo2/app/x/util.py": '''
def go():
    return 2
''',
    "repo1/app/api/endpoints/ai_results.py": '''
import asyncio
from app import crud


async def cross_ref(db, uid):
    await asyncio.sleep(1)
    return crud.user_preferences.get_profile_preferences(db, uid)
''',
    "repo1/app/api/endpoints/user_preferences.py": '''
def get_profile_preferences(db, uid):
    return None
''',
    "repo1/app/crud/crud_user_preferences.py": '''
class CRUDUserPreferences:
    def get_profile_preferences(self, db, uid):
        return None
''',
    "repo1/app/crud/crud_business_fcm.py": '''
class CRUDBusinessFcm:
    def delete_registration_id_user(self, db, rid):
        return None
''',
    "repo1/app/crud/crud_fcm.py": '''
class CRUDFcm:
    def delete_registration_id_user(self, db, rid):
        return None
''',
    "repo1/app/api/endpoints/login.py": '''
from app import crud


def logout(db, rid):
    return crud.fcm.delete_registration_id_user(db, rid)
''',
    "repo1/app/api/endpoints/business_login.py": '''
from app import crud


def logout(db, rid):
    return crud.business_fcm.delete_registration_id_user(db, rid)
''',
    "repo1/web/throttle.js": '''
export function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}
''',
}


class PythonCallTests(unittest.TestCase):
    tmp: Path
    conn: sqlite3.Connection

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="coograph-calls-"))
        for rel, body in PROJECT.items():
            path = cls.tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body.lstrip("\n"), encoding="utf-8")
        cls._build()

    @classmethod
    def _build(cls) -> None:
        db = builder.build(cls.tmp)
        cls.conn = sqlite3.connect(db)
        cls._server_paths = (server.ROOT, server.DB_PATH)
        server.ROOT, server.DB_PATH = cls.tmp, db

    @classmethod
    def tearDownClass(cls) -> None:
        server.ROOT, server.DB_PATH = cls._server_paths
        cls.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def callees(self, caller: str, file: str) -> set[tuple[str, str]]:
        """(name, file) of every function `caller` (in `file`) calls."""
        rows = self.conn.execute(
            "SELECT t.name, t.file FROM edges e "
            "JOIN nodes s ON s.id = e.src JOIN nodes t ON t.id = e.dst "
            "WHERE e.kind='calls' AND s.name=? AND s.file=?",
            (caller, file),
        )
        return set(rows)

    def test_plain_module_call(self):
        self.assertIn(("verify_receipt", "repo1/app/services/ios/iap_service.py"),
                      self.callees("buy", "repo1/app/endpoints/premium.py"))

    def test_aliased_import(self):
        self.assertIn(("verify_receipt", "repo1/app/services/ios/iap_service.py"),
                      self.callees("restore", "repo1/app/endpoints/premium.py"))

    def test_same_name_in_two_repos_prefers_callers_repo(self):
        self.assertEqual({("go", "repo1/app/x/util.py")},
                         self.callees("start", "repo1/app/main.py"))

    def test_unique_method_name_links(self):
        self.assertEqual({("recalculate_score", "repo1/app/models/policy.py")},
                         self.callees("rescore", "repo1/app/main.py"))

    def test_common_name_does_not_link(self):
        # Policy.commit exists, but `session.commit()` must not point at it.
        self.assertEqual(set(), self.callees("commit_it", "repo1/app/endpoints/premium.py"))

    def test_ambiguous_name_does_not_link(self):
        self.assertEqual(set(), self.callees("process_it", "repo1/app/endpoints/premium.py"))

    def test_chained_object_emits_nothing(self):
        self.assertEqual(set(), self.callees("checkout", "repo1/app/endpoints/premium.py"))

    def test_python_call_never_links_into_another_language(self):
        callees = self.callees("cross_ref", "repo1/app/api/endpoints/ai_results.py")
        self.assertNotIn(("sleep", "repo1/web/throttle.js"), callees)

    def test_earlier_chain_parts_pick_the_crud_module(self):
        # `crud.user_preferences.X` is the CRUD class, not the endpoint file
        # that happens to be named exactly `user_preferences.py`.
        self.assertEqual(
            {("get_profile_preferences", "repo1/app/crud/crud_user_preferences.py")},
            self.callees("cross_ref", "repo1/app/api/endpoints/ai_results.py"))

    def test_closest_name_wins_a_suffix_tie(self):
        self.assertEqual(
            {("delete_registration_id_user", "repo1/app/crud/crud_fcm.py")},
            self.callees("logout", "repo1/app/api/endpoints/login.py"))

    def test_callers_of_covers_every_function_with_the_name(self):
        rows = server.query_graph("callers_of", "delete_registration_id_user")
        self.assertEqual(
            {(r["file"], r["target_file"]) for r in rows},
            {("repo1/app/api/endpoints/login.py", "repo1/app/crud/crud_fcm.py"),
             ("repo1/app/api/endpoints/business_login.py", "repo1/app/crud/crud_business_fcm.py")})

    def test_callees_of_covers_every_function_with_the_name(self):
        rows = server.query_graph("callees_of", "logout")
        self.assertEqual(
            {(r["source_file"], r["file"]) for r in rows},
            {("repo1/app/api/endpoints/login.py", "repo1/app/crud/crud_fcm.py"),
             ("repo1/app/api/endpoints/business_login.py", "repo1/app/crud/crud_business_fcm.py")})

    def test_bare_and_self_calls_unchanged(self):
        self.assertEqual({("helper", "repo1/app/main.py")},
                         self.callees("local", "repo1/app/main.py"))
        self.assertEqual({("normalise", "repo1/app/models/policy.py")},
                         self.callees("recalculate_score", "repo1/app/models/policy.py"))

    def test_update_keeps_resolved_edges(self):
        before = self.conn.execute("SELECT COUNT(*) FROM edges WHERE kind='calls'").fetchone()[0]
        lonely = self.tmp / "repo1/app/lonely.py"
        lonely.write_text("def lonely():\n    return 0\n", encoding="utf-8")
        try:
            builder.update(self.tmp)
            after = self.conn.execute("SELECT COUNT(*) FROM edges WHERE kind='calls'").fetchone()[0]
            self.assertEqual(before, after)
            self.assertIn(("verify_receipt", "repo1/app/services/ios/iap_service.py"),
                          self.callees("buy", "repo1/app/endpoints/premium.py"))
        finally:
            lonely.unlink()


if __name__ == "__main__":
    unittest.main()
