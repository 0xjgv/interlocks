"""Tests for harness.tasks.mutation."""

import unittest


class TestMutation(unittest.TestCase):
    def test_cmd_mutation_importable(self) -> None:
        from harness.tasks.mutation import cmd_mutation

        self.assertTrue(callable(cmd_mutation))
