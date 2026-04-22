"""Tests for harness.stages.setup_hooks."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.stages.setup_hooks import _ensure_stop_hook


class TestSetupHooks(unittest.TestCase):
    def test_ensure_stop_hook_creates_stop_hook_settings(self) -> None:
        settings = _ensure_stop_hook({}, "python -m harness.cli post-edit")

        self.assertEqual(
            settings["hooks"]["Stop"],
            [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python -m harness.cli post-edit",
                        }
                    ]
                }
            ],
        )

    def test_ensure_stop_hook_preserves_existing_settings_and_avoids_duplicates(self) -> None:
        settings = {
            "theme": "dark",
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "existing command",
                            }
                        ]
                    }
                ]
            },
        }

        _ensure_stop_hook(settings, "python -m harness.cli post-edit")
        _ensure_stop_hook(settings, "python -m harness.cli post-edit")

        self.assertEqual(settings["theme"], "dark")
        stop_entries = settings["hooks"]["Stop"]
        commands = [
            hook["command"]
            for entry in stop_entries
            for hook in entry.get("hooks", [])
            if isinstance(hook, dict) and hook.get("type") == "command"
        ]
        self.assertEqual(commands.count("existing command"), 1)
        self.assertEqual(commands.count("python -m harness.cli post-edit"), 1)
        self.assertEqual(len(stop_entries), 1)

    def test_ensure_stop_hook_appends_into_existing_nested_hooks_array(self) -> None:
        settings = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "existing command",
                            }
                        ]
                    }
                ]
            }
        }

        _ensure_stop_hook(settings, "python -m harness.cli post-edit")

        self.assertEqual(
            settings["hooks"]["Stop"],
            [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "existing command",
                        },
                        {
                            "type": "command",
                            "command": "python -m harness.cli post-edit",
                        },
                    ]
                }
            ],
        )

    def test_ensure_stop_hook_normalizes_duplicate_post_edit_hooks(self) -> None:
        settings = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "uv run harness post-edit",
                            },
                            {
                                "type": "command",
                                "command": "/example/venv/bin/python -m harness.cli post-edit",
                            },
                        ]
                    },
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/example/venv/bin/python3 -m harness.cli post-edit",
                            },
                            {
                                "type": "command",
                                "command": "existing command",
                            },
                        ]
                    },
                ]
            }
        }

        _ensure_stop_hook(settings, "python -m harness.cli post-edit")

        self.assertEqual(
            settings["hooks"]["Stop"],
            [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "existing command",
                        },
                        {
                            "type": "command",
                            "command": "python -m harness.cli post-edit",
                        },
                    ]
                }
            ],
        )

    def test_cmd_hooks_writes_hook_file_and_settings(self) -> None:
        from harness.stages.setup_hooks import cmd_hooks

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("harness.stages.setup_hooks.Path", lambda value: root / value):
                cmd_hooks()

            pre_commit = (root / ".git/hooks/pre-commit").read_text(encoding="utf-8")
            settings = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))

        self.assertIn("-m harness.cli pre-commit", pre_commit)
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)
        self.assertEqual(settings["hooks"]["Stop"][0]["hooks"][0]["type"], "command")
        command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertTrue(command.endswith("-m harness.cli post-edit"))
