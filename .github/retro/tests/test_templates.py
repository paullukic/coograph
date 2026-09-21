"""Template invariants that a careless edit would otherwise ship silently.

Run:  python -m unittest discover .github/retro/tests
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

CONFIG_TEMPLATES = [
    ROOT / "openspec" / "config.yaml",
    ROOT / "plugin" / "template" / "openspec" / "config.yaml",
]
AGENT_DIRS = [ROOT / ".github" / "agents", ROOT / "plugin" / "agents"]


class ModelsAreNeverDefaulted(unittest.TestCase):
    """A fresh install must not choose models for anyone."""

    def test_config_ships_unset(self) -> None:
        for path in CONFIG_TEMPLATES:
            with self.subTest(path=path.name):
                self.assertTrue(path.exists(), path)
                text = path.read_text(encoding="utf-8")
                self.assertIn("models:", text, "the models block documents the feature")
                mode = re.search(r"^\s*mode:\s*(\w+)", text, re.MULTILINE)
                self.assertIsNotNone(mode, "models.mode must be present")
                self.assertEqual(mode.group(1), "unset",
                                 "shipping any other mode picks for the user")

    def test_preset_ships_commented_out(self) -> None:
        for path in CONFIG_TEMPLATES:
            with self.subTest(path=path.name):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if re.match(r"^\s+(explore|reviewer|debugger|planner|verifier|retro|search):", line):
                        self.fail(f"{path.name} ships a live preset entry: {line.strip()}")

    def test_catalog_ships_commented_out(self) -> None:
        """The catalogue is the project's. Shipping a live one picks a provider."""
        for path in CONFIG_TEMPLATES:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("catalog:", text,
                              "the catalogue must be documented as an example")
                for line in text.splitlines():
                    if re.match(r"^\s*catalog:", line) and not line.lstrip().startswith("#"):
                        self.fail(f"{path.name} ships a live catalog: {line.strip()}")
                    if re.match(r"^\s+(cheap|mid|capable|top):\s*\{", line):
                        self.fail(f"{path.name} ships a live catalog entry: {line.strip()}")

    def test_no_agent_pins_a_model(self) -> None:
        found = []
        for directory in AGENT_DIRS:
            if not directory.is_dir():
                continue
            for agent in directory.glob("*.md"):
                head = agent.read_text(encoding="utf-8").split("---")[1:2]
                if head and re.search(r"^model:", head[0], re.MULTILINE):
                    found.append(agent.name)
        self.assertEqual(found, [], "agents must inherit unless the user opts in")


class ReachIsStatedAccurately(unittest.TestCase):
    """The suggestion must not promise tools it cannot reach, or refuse ones it can."""

    SKILL = ROOT / ".github" / "skills" / "coograph-suggest-multi-models" / "SKILL.md"

    def setUp(self) -> None:
        self.text = self.SKILL.read_text(encoding="utf-8")

    def test_the_five_delegating_tools_are_named(self) -> None:
        for tool in ("Claude Code", "Cursor", "VS Code Copilot", "Codex CLI", "OpenCode"):
            with self.subTest(tool=tool):
                self.assertIn(tool, self.text)

    def test_claude_code_is_no_longer_the_only_one(self) -> None:
        self.assertNotIn("Claude Code only", self.text)
        self.assertNotIn("and nowhere else", self.text)

    def test_aider_and_cline_are_not_promised(self) -> None:
        """They do not delegate. 'Coming soon' implies work that will not arrive."""
        for tool in ("Aider", "Cline"):
            with self.subTest(tool=tool):
                self.assertIn(tool, self.text)
        self.assertNotIn("coming soon", self.text.lower())

    def test_the_catalogue_is_never_inferred(self) -> None:
        self.assertIn("Never infer a catalogue", self.text)


class CommandsCarryTheModelFooter(unittest.TestCase):
    """The footer is the only surface that proves a mapping was honoured."""

    DELEGATING = [
        "coograph-review", "coograph-verify", "coograph-debug",
        "coograph-search", "coograph-plan", "coograph-new-ticket", "coograph-retro",
    ]

    def test_every_delegating_command_explains_the_footer(self) -> None:
        missing = []
        for name in self.DELEGATING:
            path = ROOT / ".claude" / "commands" / f"{name}.md"
            if not path.exists():
                missing.append(f"{name} (file absent)")
                continue
            text = path.read_text(encoding="utf-8")
            if "## Models" not in text or "models:" not in text:
                missing.append(name)
        self.assertEqual(missing, [], "these delegate but never say which model ran")


if __name__ == "__main__":
    unittest.main()
