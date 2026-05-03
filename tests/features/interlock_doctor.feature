@doctor
Feature: interlocks doctor adoption diagnostic
  As a user bootstrapping interlocks on a fresh checkout
  I want `interlocks doctor` to report readiness, blockers, warnings, and next steps
  So that I can decide whether to run local checks or fix setup first

  # req: doctor-readiness
  Scenario: Doctor reports adoption readiness
    Given I run "interlocks doctor"
    Then the output contains "── Readiness"
    And the output contains "── Detected Configuration"
    And the output contains "── Setup Checklist"
    And the output contains "── Blockers"
    And the output contains "── Warnings"
    And the output contains "── Next Steps"
    And the output contains "src_dir"

  # req: doctor-setup-checklist
  Scenario: Setup Checklist surfaces artifact rows with tag labels
    Given I run "interlocks doctor"
    Then the output contains "[pyproject]"
    And the output contains "[src dir]"
    And the output contains "[ci workflow]"

  # req: doctor-crash-reports
  Scenario: Setup Checklist surfaces the crash-reports cache state
    Given I run "interlocks doctor"
    Then the output contains "[crash reports]"
    And the output contains "cached"
