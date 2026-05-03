@crash
Feature: interlocks CLI crash boundary
  As a user who hit a bug in interlocks itself
  I want a clean traceback and an actionable next step
  So that the maintainer can fix the bug and I can keep shipping

  # req: crash-boundary-prints-issue-url
  Scenario: Internal crash captures and opens a GitHub URL when accepted
    Given I run "interlocks lint" with INTERLOCKS_CRASH_INJECT=lint and answer yes to the crash report prompt
    Then the exit code is 1
    And stderr contains "Report this crash to the interlocks maintainers? Y/n"
    And stderr contains "github.com/0xjgv/interlocks/issues/new"
    And stderr contains "RuntimeError"
    And stderr contains "injected for crash boundary test"
    And a crash file exists in the cache directory

  # req: crash-user-error-no-capture
  Scenario: User-facing config error prints a clean line without capture
    Given a project without a pyproject.toml
    When I run "interlocks check"
    Then the exit code is 2
    And stderr contains "interlocks:"
    And stderr does not contain "github.com/0xjgv/interlocks/issues/new"
    And no crash file exists in the cache directory

  # req: crash-consent-off-suppresses-transport
  Scenario: Declining the crash-report prompt suppresses URL but writes local file
    Given I run "interlocks lint" with INTERLOCKS_CRASH_INJECT=lint and answer no to the crash report prompt
    Then the exit code is 1
    And stderr contains "RuntimeError"
    And stderr does not contain "github.com/0xjgv/interlocks/issues/new"
    And a crash file exists in the cache directory

  Scenario: Non-interactive crash writes local file without reporting
    Given I run "interlocks lint" with INTERLOCKS_CRASH_INJECT=lint
    Then the exit code is 1
    And stderr contains "RuntimeError"
    And stderr does not contain "Report this crash to the interlocks maintainers? Y/n"
    And stderr does not contain "github.com/0xjgv/interlocks/issues/new"
    And a crash file exists in the cache directory

  # req: crash-dedup-suppresses-transport
  Scenario: Repeat crash within the dedup window suppresses transport
    Given I run "interlocks lint" with INTERLOCKS_CRASH_INJECT=lint and answer yes to the crash report prompt
    And the first run printed a GitHub issue URL
    When I run "interlocks lint" again with INTERLOCKS_CRASH_INJECT=lint and the same cache directory
    Then the exit code is 1
    And stderr contains "RuntimeError"
    And stderr does not contain "github.com/0xjgv/interlocks/issues/new"

  # req: crash-gate-failure-no-capture
  Scenario: Real subprocess gate failure does not enter the crash boundary
    Given a project whose lint gate will fail
    When I run "interlocks lint"
    Then the exit code is not 0
    And stderr does not contain "github.com/0xjgv/interlocks/issues/new"
    And no crash file exists in the cache directory
