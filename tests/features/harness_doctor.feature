Feature: harness doctor preflight
  As a user bootstrapping pyharness on a fresh checkout
  I want `harness doctor` to report my project layout and tool availability
  So that I can diagnose a broken setup at a glance

  Scenario: Doctor reports layout and tool resolution
    Given I run "harness doctor"
    Then the output contains "Project:"
    And the output contains "Tools:"
    And the output contains "Venv:"
    And the output contains "Summary:"
    And the output contains "src_dir"
