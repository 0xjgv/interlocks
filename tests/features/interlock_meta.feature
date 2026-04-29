@meta
Feature: interlocks meta commands
  As a user adopting interlocks in a fresh project
  I want the meta commands (acceptance, init-acceptance, setup-hooks) to behave safely
  So that bootstrapping a repo is predictable end-to-end

  @smoke
  # req: meta-help-no-project
  Scenario: help runs cleanly without a project
    Given a tmp project with no features directory
    When I run "interlocks help" in the tmp project
    Then the command exits successfully

  # req: meta-acceptance-noop
  Scenario: Acceptance is a silent no-op when features/ is missing
    Given a tmp project with no features directory
    When I run "interlocks acceptance" in the tmp project
    Then the command exits successfully

  # req: meta-init-acceptance
  Scenario: init-acceptance scaffolds the canonical layout and refuses to overwrite
    Given a tmp project without tests/features/
    When I run "interlocks init-acceptance" in the tmp project
    Then the command exits successfully
    And the file "tests/features/example.feature" exists in the tmp project
    And the file "tests/step_defs/test_example.py" exists in the tmp project
    And the file "tests/step_defs/conftest.py" exists in the tmp project
    When I run "interlocks init-acceptance" in the tmp project a second time
    Then the command exits with a non-zero status

  # req: meta-setup-hooks
  Scenario: setup-hooks installs an executable pre-commit hook
    Given a tmp project with a .git directory
    When I run "interlocks setup-hooks" in the tmp project
    Then the command exits successfully
    And the pre-commit hook exists in the tmp project
    And the pre-commit hook is executable

  # req: meta-setup-skill-installs
  Scenario: setup-skill writes the bundled SKILL.md
    Given a bare tmp project
    When I run "interlocks setup-skill" in the tmp project
    Then the command exits successfully
    And the file ".claude/skills/interlocks/SKILL.md" exists in the tmp project
    And the SKILL.md in the tmp project matches the bundled copy

  # req: meta-setup-skill-idempotent
  Scenario: setup-skill is idempotent on re-run
    Given a bare tmp project
    When I run "interlocks setup-skill" in the tmp project
    Then the command exits successfully
    When I run "interlocks setup-skill" in the tmp project a second time
    Then the command exits successfully
    And the SKILL.md in the tmp project matches the bundled copy
