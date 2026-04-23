Feature: Greenfield scaffold via `harness init`
  As a user starting a new Python project
  I want `harness init` to drop a working pyproject.toml and tests/ layout
  So that `harness check` has something to run from the first commit

  Scenario: Empty directory is scaffolded
    Given an empty directory
    When I run "harness init" there
    Then the command exits successfully
    And the file "pyproject.toml" exists
    And the file "tests/__init__.py" exists
    And the file "tests/test_smoke.py" exists

  Scenario: Existing pyproject.toml is preserved
    Given a directory containing a pyproject.toml
    When I run "harness init" there
    Then the command exits with a non-zero status
    And the existing pyproject.toml is unchanged
    And the file "tests/__init__.py" does not exist
