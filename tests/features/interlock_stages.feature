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
  Scenario: `interlocks check` blocks on attribution failure when enforced
    Given a tmp project with behavior-attribution failure
    When I run "interlocks check" in the tmp project
    Then the stage exits 1
    And the stage output contains "[attribution]"

  # req: stage-ci
  Scenario: `interlocks ci` blocks on behavior attribution when enforced
    Given a tmp project with behavior-attribution failure
    When I run "interlocks ci" in the tmp project
    Then the stage exits 1
    And the stage output contains "behavior-attribution"

  # req: stage-check
  Scenario: `interlocks check --changed` short-circuits when no Python files changed
    Given a minimal tmp project initialized as a git repo
    When I run "interlocks check --changed=HEAD" in the tmp project
    Then the stage exits 0
    And the stage output contains "no Python files changed"

  # req: stage-check
  Scenario: `interlocks check --changed` scopes file-level gates and skips graph-wide gates
    Given a minimal tmp project initialized as a git repo
    And the tmp project has a changed Python file
    When I run "interlocks check --changed=HEAD" in the tmp project
    Then the stage exits 0
    And the stage output contains "Scope"
    And the stage output contains "changed vs HEAD"
    And the stage output contains "skipped under --changed"

  # req: stage-check
  Scenario: `interlocks check --changed` honors changed_ref from pyproject
    Given a minimal tmp project initialized as a git repo
    And the tmp project sets changed_ref to "HEAD"
    When I run "interlocks check --changed" in the tmp project
    Then the stage exits 0
    And the stage output contains "changed vs HEAD"

  # req: stage-check
  Scenario: `interlocks check --changed` includes top-level files in flat-layout projects
    Given a flat-layout tmp project initialized as a git repo
    And the tmp project has an untracked top-level Python file
    When I run "interlocks check --changed=HEAD" in the tmp project
    Then the stage exits 0
    And the stage output contains "Scope"
    And the stage output contains "changed vs HEAD"

  # req: stage-check
  Scenario: `interlocks check --changed` ignores non-Python file changes
    Given a minimal tmp project initialized as a git repo
    And the tmp project has an untracked Markdown file
    When I run "interlocks check --changed=HEAD" in the tmp project
    Then the stage exits 0
    And the stage output contains "no Python files changed"

  # req: stage-check
  Scenario: `interlocks check --changed` exits cleanly outside a git repo
    Given a minimal tmp project that is not a git repo
    When I run "interlocks check --changed=HEAD" in the tmp project
    Then the stage exits 0
    And the stage output contains "no Python files changed"

  # req: stage-baseline
  Scenario: `interlocks baseline show` reports the recorded floor as JSON
    Given a tmp project on the progressive preset with a recorded baseline floor
    When I run "interlocks baseline show --json" in the tmp project
    Then the stage exits 0
    And the stage output contains "coverage_min"
    And the stage output contains "advanced_from_sha"

  # req: stage-check
  Scenario: `interlocks check` does not enforce required acceptance when run_acceptance_in_check is false
    Given a tmp project with require_acceptance true and run_acceptance_in_check false
    When I run "interlocks check" in the tmp project
    Then the stage exits 0

  # req: stage-check
  Scenario: `interlocks check` fails with remediation when acceptance is required in check and features dir is missing
    Given a tmp project with require_acceptance true and run_acceptance_in_check true
    When I run "interlocks check" in the tmp project
    Then the stage exits 1
    And the stage output contains "init-acceptance"

  # req: stage-ci
  Scenario: `interlocks ci` fails with remediation when acceptance is required and features dir is missing
    Given a tmp project with require_acceptance true
    When I run "interlocks ci" in the tmp project
    Then the stage exits 1
    And the stage output contains "init-acceptance"
