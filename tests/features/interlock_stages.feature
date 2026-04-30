@stages
Feature: interlocks stage commands on a minimal inline project
  As a downstream adopter of interlocks
  I want each stage (check / pre-commit / ci / nightly) to run cleanly on a
  trivial project with no surprises
  So that my real projects can rely on the same exit-code + output contract

  # req: stage-check
  Scenario: `interlocks check` greenlights a clean project
    Given a minimal tmp project
    When I run "interlocks check" in the tmp project
    Then the stage exits 0
    And the stage output contains "Quality Checks"
    And the stage output contains "[fix]"
    And the stage output contains "[test]"

  # req: stage-pre-commit
  Scenario: `interlocks pre-commit` no-ops when nothing is staged
    Given a minimal tmp project
    When I run "interlocks pre-commit" in the tmp project
    Then the stage exits 0
    And the stage output contains "No staged Python files"

  # req: stage-ci
  Scenario: `interlocks ci` runs the full verification pipeline
    Given a minimal tmp project
    When I run "interlocks ci" in the tmp project
    Then the stage exits 0
    And the stage output contains "CI Checks"
    And the stage output contains "[lint]"
    And the stage output contains "[coverage]"

  # req: stage-nightly
  Scenario: `interlocks nightly` runs coverage + mutation (bounded runtime)
    Given a minimal tmp project
    When I run "interlocks nightly" in the tmp project
    Then the stage exits 0
    And the stage output contains "Nightly"
    And the stage output contains "[coverage]"
    And the stage output contains "Mutation"

  # req: stage-check
  Scenario: `interlocks check` reports attribution advisory without blocking
    Given a tmp project with behavior-attribution failure
    When I run "interlocks check" in the tmp project
    Then the stage exits 0
    And the stage output contains "[attribution]"

  # req: stage-ci
  Scenario: `interlocks ci` blocks on behavior attribution when enforced
    Given a tmp project with behavior-attribution failure
    When I run "interlocks ci" in the tmp project
    Then the stage exits 1
    And the stage output contains "behavior-attribution"
