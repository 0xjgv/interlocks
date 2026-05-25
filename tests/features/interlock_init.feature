@init
Feature: Greenfield scaffold via `interlocks init`
  As a user starting a new Python project
  I want `interlocks init` to drop a working pyproject.toml and tests/ layout
  So that `interlocks check` has something to run from the first commit

  # req: init-empty-dir
  Scenario: Empty directory is scaffolded
    Given an empty directory
    When I run "interlocks init" there
    Then the command exits successfully
    And the file "pyproject.toml" exists
    And the file "tests/__init__.py" exists
    And the file "tests/test_smoke.py" exists

  # req: init-preserve-tests-dir
  Scenario: Existing tests directory is preserved while missing scaffold files are created
    Given a directory containing an empty tests directory
    When I run "interlocks init" there
    Then the command exits successfully
    And the file "pyproject.toml" exists
    And the file "tests/__init__.py" exists
    And the file "tests/test_smoke.py" exists
    And the output contains "created tests/test_smoke.py"

  # req: init-preserve-existing
  Scenario: Existing pyproject.toml is preserved
    Given a directory containing a pyproject.toml
    When I run "interlocks init" there
    Then the command exits with a non-zero status
    And the existing pyproject.toml is unchanged
    And the file "tests/__init__.py" does not exist
