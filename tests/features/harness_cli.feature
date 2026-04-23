Feature: Harness CLI surface area
  As a user about to run the quality gates
  I want `harness help` to list every command I rely on
  So that I can see at a glance what's wired up

  Scenario: Core commands are advertised
    Given I run "harness help"
    Then the output lists the command "fix"
    And the output lists the command "format"
    And the output lists the command "lint"
    And the output lists the command "typecheck"
    And the output lists the command "test"
    And the output lists the command "audit"
    And the output lists the command "deps"
    And the output lists the command "arch"
    And the output lists the command "acceptance"
    And the output lists the command "init"
    And the output lists the command "init-acceptance"
    And the output lists the command "coverage"
    And the output lists the command "crap"
    And the output lists the command "mutation"
    And the output lists the command "check"
    And the output lists the command "pre-commit"
    And the output lists the command "ci"
    And the output lists the command "nightly"
    And the output lists the command "post-edit"
    And the output lists the command "setup-hooks"
    And the output lists the command "clean"
    And the output lists the command "version"
    And the output lists the command "help"

  Scenario: harness version prints 1.0.0
    Given I run "harness version"
    Then the output contains "1.0.0"
