@cli
Feature: interlocks CLI surface area
  As a user about to run the quality gates
  I want `interlocks help` to list every command I rely on
  So that I can see at a glance what's wired up

  # req: cli-commands
  Scenario: Core commands are advertised
    Given I run "interlocks help"
    Then the output lists the command "fix"
    And the output lists the command "format"
    And the output lists the command "lint"
    And the output lists the command "typecheck"
    And the output lists the command "test"
    And the output lists the command "audit"
    And the output lists the command "deps"
    And the output lists the command "deps-freshness"
    And the output lists the command "arch"
    And the output lists the command "acceptance"
    And the output lists the command "behavior-attribution"
    And the output lists the command "init"
    And the output lists the command "init-acceptance"
    And the output lists the command "setup"
    And the output lists the command "agents"
    And the output lists the command "setup-skill"
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
    And the output lists the command "evaluate"
    And the output lists the command "config"
    And the output lists the command "version"
    And the output lists the command "help"

  @smoke
  # req: cli-version
  Scenario: interlocks version prints 0.1.4
    Given I run "interlocks version"
    Then the output contains "0.1.4"

  # req: cli-help-crash-reports
  Scenario: help text surfaces the crash_reports key and cache directory
    Given I run "interlocks help"
    Then the output contains "── Crash Reports"
    And the output contains "~/.cache/interlocks/crashes/"
    And the output contains "crash_reports"
    And the output contains "INTERLOCKS_CRASH_REPORTS overrides"

  # req: cli-quiet
  Scenario: interlocks help --quiet skips banner and section headers
    Given I run "interlocks help --quiet"
    Then the output does not contain "command=help"
    And the output does not contain "── "

  # req: cli-command-help
  Scenario: command-specific help is non-destructive
    Given I run "interlocks coverage --help"
    Then the output contains "Usage: interlocks coverage"
    And the output contains "[coverage]"
    And the output does not contain "coverage report --fail-under"
    And the output does not contain "failed"

  # req: cli-config
  Scenario: Agent reads config reference
    Given I run "interlocks config"
    Then the output contains "preset"
    And the output contains "coverage_min"
    And the output contains "audit_severity_threshold"
    And the output contains "pr_ci_runtime_budget_seconds"
    And the output contains "crash_reports"
    And the output contains "── Precedence"
    And the output contains "── Examples"
    And the output does not contain "user-global"

  # req: cli-evaluate-guidance
  Scenario: Evaluate gap guidance includes closure command
    Given I run "interlocks evaluate" on a project with a traceability gap
    Then the output contains "── Next Actions"
    And the output contains "Close with `"
