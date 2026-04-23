Feature: Harness meta commands
  As a user adopting harness in a fresh project
  I want the meta commands (acceptance, init-acceptance, setup-hooks) to behave safely
  So that bootstrapping a repo is predictable end-to-end

  Scenario: Acceptance is a silent no-op when features/ is missing
    Given a tmp project with no features directory
    When I run "harness acceptance" in the tmp project
    Then the command exits successfully

  Scenario: init-acceptance scaffolds the canonical layout and refuses to overwrite
    Given a tmp project without tests/features/
    When I run "harness init-acceptance" in the tmp project
    Then the command exits successfully
    And the file "tests/features/example.feature" exists in the tmp project
    And the file "tests/step_defs/test_example.py" exists in the tmp project
    And the file "tests/step_defs/conftest.py" exists in the tmp project
    When I run "harness init-acceptance" in the tmp project a second time
    Then the command exits with a non-zero status

  Scenario: setup-hooks installs an executable pre-commit hook
    Given a tmp project with a .git directory
    When I run "harness setup-hooks" in the tmp project
    Then the command exits successfully
    And the pre-commit hook exists in the tmp project
    And the pre-commit hook is executable
