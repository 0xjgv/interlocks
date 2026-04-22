Feature: Harness CLI surface area
  As a user about to run the quality gates
  I want `harness help` to list every command I rely on
  So that I can see at a glance what's wired up

  Scenario: Core commands are advertised
    Given I run "harness help"
    Then the output lists the command "acceptance"
    And the output lists the command "init-acceptance"
    And the output lists the command "check"
    And the output lists the command "ci"
