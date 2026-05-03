@tasks
Feature: interlocks task commands run against a real tmp project
  As a user running quality gates
  I want each `interlocks <task>` to behave sensibly on a freshly-scaffolded project
  So that the tool is safe to adopt on any layout

  # req: task-audit
  Scenario: audit reports no vulnerabilities for a project with no deps
    Given a tmp project with layout "audit"
    When I run "interlocks audit" in that project
    Then the exit code is 0 or the output mentions "No known vulnerabilities"

  # req: task-deps
  Scenario: deps flags a declared-but-unused dependency
    Given a tmp project with layout "deps"
    When I run "interlocks deps" in that project
    Then the exit code is not 0
    And the output contains "DEP002"

  # req: task-arch
  Scenario: arch passes with the default contract when src and tests are packages
    Given a tmp project with layout "arch"
    When I run "interlocks arch" in that project
    Then the exit code is 0
    And the output contains "[arch]"

  # req: task-coverage
  Scenario: coverage passes when a trivial test exercises the module
    Given a tmp project with layout "coverage"
    When I run "interlocks coverage --min=0" in that project
    Then the exit code is 0
    And the output contains "[coverage]"

  # req: task-coverage-uv-injection
  Scenario: uv coverage uses Interlocks-supplied Coverage.py
    Given a tmp project with layout "uv-coverage"
    When I inspect "interlocks coverage" in that project
    Then the coverage commands inject Coverage.py through uv
    And the coverage commands do not call "uv run coverage"

  # req: task-crap
  Scenario: crap passes when no function exceeds the threshold
    Given a tmp project with layout "crap"
    When I run "interlocks crap" in that project
    Then the exit code is 0
    And the output contains "CRAP"

  # req: task-mutation
  Scenario: mutation skips cleanly without coverage data
    Given a tmp project with layout "mutation"
    When I run "interlocks mutation" in that project
    Then the exit code is 0
    And the output contains "mutation"

  # req: task-mutation-incremental
  Scenario: incremental mutation skips when no src files changed
    Given a tmp project with layout "mutation-incremental-empty"
    When I run "interlocks mutation --changed-only" in that project
    Then the exit code is 0
    And the output contains "no changed src files"

  # req: task-acceptance-required
  Scenario: acceptance fails when require_acceptance is true and features dir is missing
    Given a tmp project with layout "require-acceptance-no-features"
    When I run "interlocks acceptance" in that project
    Then the exit code is not 0
    And the output contains "interlocks init-acceptance"

  # req: task-acceptance-behavior-success
  Scenario: acceptance passes when required behavior IDs are covered
    Given a tmp project with layout "require-acceptance-behavior-covered"
    When I run "interlocks acceptance" in that project
    Then the exit code is 0
    And the output contains "[acceptance]"

  # req: task-acceptance-behavior-uncovered
  Scenario: acceptance reports uncovered behavior IDs when markers are missing
    Given a tmp project with layout "require-acceptance-behavior-uncovered"
    When I run "interlocks acceptance" in that project
    Then the exit code is not 0
    And the output contains "uncovered behavior ID"

  # req: task-acceptance-behavior-stale
  Scenario: acceptance reports stale behavior IDs when markers drift
    Given a tmp project with layout "require-acceptance-behavior-stale"
    When I run "interlocks acceptance" in that project
    Then the exit code is not 0
    And the output contains "stale behavior ID"

  # req: task-acceptance-trace-advisory
  Scenario: advisory trace evidence does not block passing acceptance coverage
    Given a tmp project with layout "require-acceptance-trace-advisory"
    When I run "interlocks acceptance" in that project
    Then the exit code is 0
    And the output contains "[acceptance]"

  # req: task-behavior-attribution-success
  Scenario: behavior-attribution passes when every claim reaches its symbol
    Given a tmp project with layout "behavior-attribution-success"
    When I run "interlocks behavior-attribution" in that project
    Then the exit code is 0
    And the output contains "[attribution]"

  # req: task-behavior-attribution-unattributed
  Scenario: behavior-attribution flags a mis-attributed scenario claim
    Given a tmp project with layout "behavior-attribution-unattributed"
    When I run "interlocks behavior-attribution" in that project
    Then the exit code is not 0
    And the output contains "mis-attributed"

  # req: task-behavior-attribution-unresolved
  Scenario: behavior-attribution flags unresolved behavior symbols
    Given a tmp project with layout "behavior-attribution-unresolved"
    When I run "interlocks attribution" in that project
    Then the exit code is not 0
    And the output contains "unresolved behavior symbols"

