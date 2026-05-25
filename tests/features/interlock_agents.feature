@agents
Feature: Register interlocks usage via `interlocks agents`
  As a user adopting interlocks in an existing repo
  I want `interlocks agents` to wire up AGENTS.md and CLAUDE.md
  So that coding agents discover the right commands without manual edits

  # req: agents-create-missing
  Scenario: Missing agent docs are created with the canonical block
    Given an empty directory
    When I run "interlocks agents" there
    Then the command exits successfully
    And the output contains "[agent docs]"
    And the output contains "registered"
    And the file "AGENTS.md" exists
    And the file "CLAUDE.md" exists
    And "AGENTS.md" contains "interlocks check"
    And "CLAUDE.md" contains "interlocks check"

  # req: agents-append-when-missing
  Scenario: Existing files without an interlocks reference get the block appended
    Given a directory with AGENTS.md "# Existing" and CLAUDE.md "# Project"
    When I run "interlocks agents" there
    Then the command exits successfully
    And the output contains "[agent docs]"
    And "AGENTS.md" starts with "# Existing"
    And "AGENTS.md" contains "interlocks check"
    And "CLAUDE.md" starts with "# Project"
    And "CLAUDE.md" contains "interlocks check"

  # req: agents-idempotent
  Scenario: Docs that already document the check stage are preserved unchanged
    Given a directory with AGENTS.md "already runs interlocks check" and CLAUDE.md "uses il check"
    When I run "interlocks agents" there
    Then the command exits successfully
    And the output contains "[agent docs]"
    And "AGENTS.md" equals "already runs interlocks check"
    And "CLAUDE.md" equals "uses il check"

  # req: agents-append-when-stage-missing
  Scenario: Stale interlocks-only mentions still get the canonical block appended
    Given a directory with AGENTS.md "see interlocks docs" and CLAUDE.md "uses interlocks"
    When I run "interlocks agents" there
    Then the command exits successfully
    And "AGENTS.md" starts with "see interlocks docs"
    And "AGENTS.md" contains "interlocks check"
    And "CLAUDE.md" starts with "uses interlocks"
    And "CLAUDE.md" contains "interlocks check"
