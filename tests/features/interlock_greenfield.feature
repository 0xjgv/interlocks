@greenfield
Feature: interlocks unblock flow on a legacy greenfield project
  As an engineer asked to land a fix in an unadopted codebase
  I want the lint-fix harness to preview safe paths without rewriting unrelated code
  So that I can unblock my PR without inheriting legacy cleanup

  Background:
    Given a legacy greenfield project with no quality-gate configuration

  # req: greenfield-check-blocks
  Scenario: `interlocks check` blocks on lint failures
    When I run "interlocks check" in the greenfield project
    Then the greenfield command exits non-zero
    And the greenfield output mentions ruff

  # req: greenfield-fix-plan-non-mutating
  Scenario: `interlocks fix-plan` previews fixes without mutating the tree
    When I run "interlocks fix-plan --base=HEAD" in the greenfield project
    Then the greenfield command exits 0
    And the file ".lintfix/plan.json" exists in the greenfield project
    And the seeded source files are unchanged
    And the plan groups candidates by classification

  # req: greenfield-fix-rule-preview
  Scenario: `interlocks fix-rule --rule=I001` previews without mutating
    When I run "interlocks fix-rule --rule=I001 --base=HEAD" in the greenfield project
    Then the greenfield command exits 0
    And the seeded source files are unchanged

  # req: greenfield-fix-optimize-non-mutating
  Scenario: `interlocks fix-optimize` selects without mutating
    When I run "interlocks fix-optimize --base=HEAD" in the greenfield project
    Then the greenfield command exits 0
    And the file ".lintfix/optimize.json" exists in the greenfield project
    And the optimize payload exposes selected and not_selected lists
    And the seeded source files are unchanged

  # req: greenfield-fix-annotate
  Scenario: `interlocks fix-annotate` emits workflow command lines
    Given I have run "interlocks fix-plan --base=HEAD" in the greenfield project
    When I run "interlocks fix-annotate" in the greenfield project
    Then the greenfield command exits 0
    And the greenfield output contains "::notice file="

  # req: greenfield-fix-metrics
  Scenario: `interlocks fix-metrics` rolls up the per-run JSON files
    Given I have run "interlocks fix-plan --base=HEAD" in the greenfield project
    When I run "interlocks fix-metrics" in the greenfield project
    Then the greenfield command exits 0
    And the file ".lintfix/metrics.json" exists in the greenfield project
    And the metrics payload exposes a sources truthtable

  # req: greenfield-setup-check
  Scenario: `interlocks setup --check` reports missing local integrations
    When I run "interlocks setup --check" in the greenfield project
    Then the greenfield command exits non-zero
    And the greenfield output contains "missing/stale"

  # req: greenfield-doctor
  Scenario: `interlocks doctor` flags the unadopted project
    When I run "interlocks doctor" in the greenfield project
    Then the greenfield output contains "Setup Checklist"
    And the greenfield output names at least one missing adoption artifact
