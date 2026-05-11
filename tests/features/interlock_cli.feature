@cli
Feature: interlocks CLI surface area
  As a user about to run the quality gates
  I want `interlocks help` to teach the common path
  So that I can see at a glance what's wired up

  # req: cli-commands
  Scenario: Default help lists start-here and common gate commands
    Given I run "interlocks help"
    Then the output lists the command "doctor"
    And the output lists the command "check"
    And the output lists the command "ci"
    And the output lists the command "setup"
    And the output lists the command "fix"
    And the output lists the command "format"
    And the output lists the command "lint"
    And the output lists the command "typecheck"
    And the output lists the command "test"
    And the output lists the command "coverage"
    And the output lists the command "audit"
    And the output lists the command "deps"
    And the output lists the command "arch"
    And the output lists the command "acceptance"
    And the output lists the command "init"
    And the output lists the command "config"
    And the output lists the command "version"
    And the output contains "help --advanced"

  # req: cli-commands-advanced
  Scenario: Advanced help lists every command including internal and alias commands
    Given I run "interlocks help --advanced"
    Then the output lists every registered command
    And the output contains "alias: attribution"

  @smoke
  # req: cli-version
  Scenario: interlocks version prints 0.2.0
    Given I run "interlocks version"
    Then the output contains "0.2.0"

  # req: cli-help-crash-reports
  Scenario: help text surfaces crash report behavior and cache directory
    Given I run "interlocks help"
    Then the output contains "── Crash Reports"
    And the output contains "~/.cache/interlocks/crashes/"
    And the output contains "interactive terminals prompt before opening a GitHub issue"

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
    And the output contains "── Precedence"
    And the output contains "── Examples"
    And the output does not contain "user-global"

  # req: cli-presets-parity
  Scenario: presets command lists all four presets including progressive
    Given I run "interlocks presets"
    Then the output contains "── Available Presets"
    And the output contains "baseline"
    And the output contains "strict"
    And the output contains "legacy"
    And the output contains "progressive"
    And the output contains "autopilot ratchet"

  # req: cli-evaluate-guidance
  Scenario: Evaluate gap guidance includes closure command
    Given I run "interlocks evaluate" on a project with a traceability gap
    Then the output contains "── Next Actions"
    And the output contains "Close with `"
