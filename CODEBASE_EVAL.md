# Automated Codebase Evaluation Checklist

## 1. Acceptance criteria

* Are Gherkin/spec files present?
* Are scenarios linked to features or PRs?
* Can acceptance tests run in CI?

## 2. Unit tests

* Does CI run the full unit test suite?
* Are important modules covered by tests?
* Are failing tests required to block merge?

## 3. Coverage

* Is coverage measured automatically?
* Is there a minimum coverage threshold?
* Are branch and line coverage both tracked?
* Does CI fail when coverage drops?

## 4. Mutation testing

* Is mutation testing configured?
* Is it run on critical modules?
* Is there a minimum mutation score?
* Does CI fail when the mutation score drops?

## 5. CRAP / complexity

* Is cyclomatic complexity measured?
* Is CRAP score measured or approximated?
* Are complexity thresholds enforced in CI?
* Does CI fail on newly introduced overly complex code?

## 6. Dependency rules

* Are architectural boundaries enforced automatically?
* Are forbidden imports checked?
* Are circular dependencies detected?
* Does CI fail when dependency rules are violated?

## 7. Security/dependency checks

* Are vulnerable dependencies detected automatically?
* Are outdated or risky packages flagged?
* Does CI fail on high-severity issues?

## 8. CI enforcement

* Are all checks required before merge?
* Are results visible in PRs?
* Can failures be reproduced locally?
* Are checks fast enough to run on every PR?

## Score

* **0 = not present**
* **1 = present but not enforced**
* **2 = enforced sometimes**
* **3 = enforced in CI and blocks merge**

The codebase is healthy when these checks are **automated, reproducible, and merge-blocking**.
