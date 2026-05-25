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
    When I run "interlocks setup --check" in the greenfield project in default mode
    Then the greenfield command exits non-zero
    And the greenfield output contains "missing/stale"
    And the greenfield output contains "next: Run `interlocks setup`"
    And the greenfield output contains "interlocks presets set progressive"

  # req: setup-refuses-non-git
  @mutmut_incompatible
  Scenario: `interlocks setup` refuses a directory that is not a git repository
    Given a project directory that is not a git repo
    When I run "interlocks setup" in the non-git project
    Then the greenfield command exits non-zero
    And no .git directory was created in the non-git project
    And the greenfield output contains "git init"

  # req: setup-default-summary
  Scenario: `interlocks setup` prints a per-artifact summary on success in default mode
    When I run "interlocks setup" in the greenfield project in default mode
    Then the greenfield command exits 0
    And the greenfield output contains "[git hook]"
    And the greenfield output contains "[claude skill]"
    And the greenfield output contains "installed"

  # req: setup-check-full-rows
  Scenario: `interlocks setup --check` prints every artifact row in default mode
    Given I have run "interlocks setup" in the greenfield project
    When I run "interlocks setup --check" in the greenfield project in default mode
    Then the greenfield command exits 0
    And the greenfield output contains "[git hook]"
    And the greenfield output contains "installed"
    And the greenfield output contains "interlocks presets set progressive"

  # req: greenfield-doctor
  Scenario: `interlocks doctor` flags the unadopted project
    When I run "interlocks doctor" in the greenfield project
    Then the greenfield output contains "Setup Checklist"
    And the greenfield output names at least one missing adoption artifact

  # req: doctor-default-shows-gaps
  Scenario: `interlocks doctor` names its gaps in default mode
    When I run "interlocks doctor" in the greenfield project in default mode
    Then the greenfield command exits 0
    And the greenfield output names at least one missing adoption gap inline

  # req: doctor-strict-exit
  Scenario: `interlocks doctor --strict` exits non-zero when blocked
    Given the greenfield project has no virtualenv
    When I run "interlocks doctor --strict" in the greenfield project
    Then the greenfield command exits non-zero

  # req: doctor-no-uvx-path-warn
  Scenario: `interlocks doctor --verbose` does not warn that uvx tools are off PATH
    When I run "interlocks doctor" in the greenfield project
    Then the greenfield output does not contain "tool not found on PATH: ruff"

  # req: ci-no-venv-skip
  Scenario: `interlocks ci` skips dependency gates without a project environment
    Given the greenfield project has no virtualenv
    When I run "interlocks ci" in the greenfield project
    Then the greenfield command exits 0
    And the greenfield output contains "no project environment"
