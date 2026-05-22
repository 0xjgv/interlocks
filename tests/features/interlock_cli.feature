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

  # req: cli-help-groups-default
  # req: cli-help-detected-summary
  Scenario: default-mode help shows group headers and a one-line Detected summary
    Given I run "interlocks help --default-mode"
    Then the output contains "Start here:"
    And the output contains "Common gates:"
    And the output contains "Detected:"
    And the output does not contain "── Thresholds"

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

  # req: cli-minimal-default
  Scenario: interlocks --quiet is rejected with exit 1
    Given I run "interlocks help --quiet"
    Then the output contains "--quiet was removed"

  # req: cli-command-help
  Scenario: command-specific help is non-destructive
    Given I run "interlocks coverage --help"
    Then the output contains "Usage: interlocks coverage"
    And the output contains "[coverage]"
    And the output does not contain "coverage report --fail-under"
    And the output does not contain "failed"

  # req: cli-unknown-flag-rejected
  Scenario: Unknown flag is rejected and names the flag
    Given I run "interlocks coverage --bogus-flag"
    Then the output contains "unknown flag --bogus-flag"

  # req: cli-task-help-lists-flags
  Scenario: Per-task help lists declared flags with defaults
    Given I run "interlocks coverage --help"
    Then the output contains "--min"
    And the output contains "coverage fail-under percentage"

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

  # req: cli-config-single-presenter
  Scenario: default-mode config emits the sectioned table only, no flat resolved block
    Given I run "interlocks config --default-mode"
    Then the output contains "coverage_min"
    And the output contains "Thresholds"
    And the output does not contain "── Resolved values"

  # req: cli-presets-default-footer
  Scenario: default-mode presets prints a Switch with footer
    Given I run "interlocks presets --default-mode"
    Then the output contains "Switch with: interlocks presets set"
    And the output does not contain "── Next Steps"

  # req: cli-evaluate-guidance
  Scenario: Evaluate gap guidance includes closure command
    Given I run "interlocks evaluate" on a project with a traceability gap
    Then the output contains "── Next Actions"
    And the output contains "Close with `"

  # req: cli-json-ci
  Scenario: ci --json emits parseable JSON with passed/gates/elapsed
    Given I run "interlocks ci --json" in a temp project
    Then stdout is a single JSON object with keys "command,passed,elapsed_seconds,gates,skipped"

  # req: cli-json-check
  Scenario: check --json emits parseable JSON with passed/gates
    Given I run "interlocks check --json" in a temp project
    Then stdout is a single JSON object with keys "command,passed,elapsed_seconds,gates"

  # req: cli-json-evaluate
  Scenario: evaluate --json emits parseable JSON with score/checks
    Given I run "interlocks evaluate --json" in a temp project
    Then stdout is a single JSON object with keys "command,score,verdict,checks"

  # req: cli-json-trust
  Scenario: trust --json emits parseable JSON in a coverage-less project
    Given I run "interlocks trust --json" in a temp project
    Then stdout is a single JSON object with keys "command,error"

  # req: cli-json-doctor
  Scenario: doctor --json emits parseable JSON with status/blockers/warnings
    Given I run "interlocks doctor --json" in a temp project
    Then stdout is a single JSON object with keys "command,status,blockers,warnings,detected,setup_checklist"

  # req: cli-json-config
  Scenario: config --json emits parseable JSON with resolved key/value/source
    Given I run "interlocks config --json" in a temp project
    Then stdout is a single JSON object with keys "command,preset,pyproject_path,keys"

  # req: cli-explain-all
  Scenario: explain --all documents every command
    Given I run "interlocks explain --all"
    Then the output lists every registered command
    And the output contains "When to use"
    And the output contains "Mutates"
    And the output contains "Exit codes"

  # req: cli-explain-one
  Scenario: explain a single command prints just that command's prose
    Given I run "interlocks explain coverage"
    Then the output contains "When to use"
    And the output does not contain "[fix]"

  # req: cli-explain-default-is-index
  Scenario: explain with no argument prints a grouped command index
    Given I run "interlocks explain"
    Then the output lists every registered command
    And the output contains "interlocks explain --all"
    And the output does not contain "When to use"
