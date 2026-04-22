Feature: Example acceptance scenario
  As a new project
  I want one runnable Gherkin scenario
  So that `harness acceptance` has something to execute

  Scenario: Arithmetic sanity
    Given the number 2
    When I add 3
    Then the result is 5
