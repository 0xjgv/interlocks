Feature: harness doctor adoption diagnostic
  As a user bootstrapping pyharness on a fresh checkout
  I want `harness doctor` to report readiness, blockers, warnings, and next steps
  So that I can decide whether to run local checks or fix setup first

  Scenario: Doctor reports adoption readiness
    Given I run "harness doctor"
    Then the output contains "── Readiness"
    And the output contains "── Detected Configuration"
    And the output contains "── Blockers"
    And the output contains "── Warnings"
    And the output contains "── Next Steps"
    And the output contains "src_dir"
