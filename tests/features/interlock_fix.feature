@fix
Feature: per-command coverage of the fix-* harness
  As an engineer adopting the lint-fix harness
  I want each fix-* subcommand to produce its documented JSON without mutating
  So that I can read the plan, the optimization, and the metrics safely

  Background:
    Given a legacy greenfield project with no quality-gate configuration

  # req: fix-plan-classifies-i001-auto
  Scenario: fix-plan classifies I001 as auto
    When I run "interlocks fix-plan --base=HEAD" in the greenfield project
    Then the greenfield command exits 0
    And the plan classifies rule "I001" as "auto"

  # req: fix-plan-classifies-f401-escrow
  Scenario: fix-plan classifies F401 as escrow
    When I run "interlocks fix-plan --base=HEAD" in the greenfield project
    Then the greenfield command exits 0
    And the plan classifies rule "F401" as "escrow"

  # req: fix-plan-skips-unsafe-only
  Scenario: fix-plan marks unsafe-only diagnostics as skip with an "unsafe" reason
    When I run "interlocks fix-plan --base=HEAD" in the greenfield project
    Then the greenfield command exits 0
    And every unsafe candidate is classified as skip with reason mentioning "unsafe"

  # req: fix-replay-writes-per-rule-stats
  Scenario: fix-replay writes per-rule statistics across a few-commit history
    Given the greenfield project has a few-commit history
    When I run "interlocks fix-replay --base=main --n=2" in the greenfield project
    Then the greenfield command exits 0
    And the replay payload exposes per-rule statistics keys

  # req: fix-optimize-empty-plan
  Scenario: fix-optimize selects nothing when the plan is empty
    Given the greenfield project working tree is clean
    When I run "interlocks fix-optimize --base=HEAD" in the greenfield project
    Then the greenfield command exits 0
    And the optimize selected list is empty

  # req: fix-optimize-no-unsafe-in-unblock
  Scenario: fix-optimize never selects unsafe fixes under the unblock budget
    When I run "interlocks fix-optimize --base=HEAD --budget=unblock" in the greenfield project
    Then the greenfield command exits 0
    And no selected candidate is unsafe

  # req: fix-annotate-missing-plan
  Scenario: fix-annotate exits 0 with no output when the plan is missing
    When I run "interlocks fix-annotate" in the greenfield project
    Then the greenfield command exits 0
    And the greenfield output has no annotation lines

  # req: fix-metrics-missing-inputs
  Scenario: fix-metrics handles missing inputs gracefully
    When I run "interlocks fix-metrics" in the greenfield project
    Then the greenfield command exits 0
    And the file ".lintfix/metrics.json" exists in the greenfield project
    And the metrics sources truthtable is all false
