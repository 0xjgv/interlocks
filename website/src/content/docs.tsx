import {
    SectionHeading,
    P,
    Code,
    CodeBlock,
    List,
    Li,
    type EditorialSection,
} from '../components/markdown';
import type { FlatTocItem, TocNodeType } from '../components/toc-tree';

function tocItem(
    href: string,
    label: string,
    opts: { level?: 0 | 1 | 2 | 3; parent?: string; prefix?: string; type?: TocNodeType } = {},
): FlatTocItem {
    return {
        href,
        label,
        type: opts.type ?? (opts.level ? 'h3' : 'h2'),
        visualLevel: (opts.level ?? 0) as FlatTocItem['visualLevel'],
        prefix: opts.prefix ?? '',
        parentHref: opts.parent ?? null,
        pageHref: '/docs/',
    };
}

export const pageContent = {
    meta: {
        title: 'pyharness Docs — Complete Reference',
        description:
            'Complete pyharness reference: every task and flag, every [tool.harness] config key, the precedence cascade, bundled defaults, Gherkin acceptance, and the setup-hooks deep-dive.',
    },

    toc: [
        tocItem('#tasks', 'Tasks'),
        tocItem('#tasks-fix', 'fix', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-format', 'format', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-lint', 'lint', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-typecheck', 'typecheck', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-test', 'test', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-acceptance', 'acceptance', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-init-acceptance', 'init-acceptance', {
            level: 1,
            parent: '#tasks',
            prefix: '├ ',
        }),
        tocItem('#tasks-audit', 'audit', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-deps', 'deps', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-arch', 'arch', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-coverage', 'coverage', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-crap', 'crap', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-mutation', 'mutation', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-clean', 'clean', { level: 1, parent: '#tasks', prefix: '├ ' }),
        tocItem('#tasks-setup-hooks', 'setup-hooks', {
            level: 1,
            parent: '#tasks',
            prefix: '├ ',
        }),
        tocItem('#tasks-help', 'help', { level: 1, parent: '#tasks', prefix: '└ ' }),
        tocItem('#config', 'Configuration'),
        tocItem('#precedence', 'Precedence Cascade'),
        tocItem('#defaults', 'Bundled Defaults'),
        tocItem('#acceptance', 'Acceptance (Gherkin)'),
        tocItem('#hooks', 'Hooks Deep-Dive'),
    ] as FlatTocItem[],

    hero: (
        <div style={{ padding: '20px 0 8px' }}>
            <p
                style={{
                    fontFamily: 'var(--font-secondary)',
                    fontStyle: 'italic',
                    fontSize: '19px',
                    fontWeight: 400,
                    lineHeight: 1.55,
                    color: 'var(--text-primary)',
                    opacity: 0.72,
                    margin: 0,
                }}
            >
                Complete reference for pyharness — every task, every config key, and every
                bundled default, grounded in the source.
            </p>
        </div>
    ),

    sections: [
        /* ── Tasks ───────────────────────────────────────────────────────────
           Source: /Users/juan/Code/pyharness/harness/cli.py:80-126 (TASK_GROUPS).
           Each task below mirrors a (name, description) entry in that list. */
        {
            content: (
                <>
                    <SectionHeading id="tasks" level={1}>
                        Tasks
                    </SectionHeading>
                    <P>
                        Every sub-command of <Code>harness</Code>, in the same order they appear in{' '}
                        <Code>TASK_GROUPS</Code>. Tasks mutate or inspect a single concern; stages
                        (<Code>check</Code>, <Code>pre-commit</Code>, <Code>ci</Code>,{' '}
                        <Code>nightly</Code>) compose them. Flags not listed here fall back to{' '}
                        <Code>[tool.harness]</Code> config.
                    </P>
                    {/* harness/cli.py:84 — "fix": (cmd_fix, "Fix lint errors with ruff") */}
                    <SectionHeading id="tasks-fix" level={2}>
                        fix
                    </SectionHeading>
                    <P>Fix lint errors with ruff. Mutates source files in place.</P>
                    <CodeBlock lang="bash">{`harness fix`}</CodeBlock>

                    {/* harness/cli.py:85 — "format": (cmd_format, "Format code with ruff") */}
                    <SectionHeading id="tasks-format" level={2}>
                        format
                    </SectionHeading>
                    <P>Format code with ruff. Mutates source files in place.</P>
                    <CodeBlock lang="bash">{`harness format`}</CodeBlock>

                    {/* harness/cli.py:86 — "lint": (cmd_lint, "Lint code with ruff (read-only)") */}
                    <SectionHeading id="tasks-lint" level={2}>
                        lint
                    </SectionHeading>
                    <P>Read-only ruff lint check. Used by CI; does not mutate files.</P>
                    <CodeBlock lang="bash">{`harness lint`}</CodeBlock>

                    {/* harness/cli.py:87 — "typecheck": (cmd_typecheck, "Type-check with basedpyright") */}
                    <SectionHeading id="tasks-typecheck" level={2}>
                        typecheck
                    </SectionHeading>
                    <P>
                        Type-check with basedpyright. Uses your{' '}
                        <Code>pyrightconfig.json</Code> or{' '}
                        <Code>[tool.basedpyright]</Code> if present; otherwise falls back to the
                        bundled <Code>harness/defaults/pyrightconfig.json</Code> (see{' '}
                        <a href="#defaults">Bundled Defaults</a>).
                    </P>
                    <CodeBlock lang="bash">{`harness typecheck`}</CodeBlock>

                    {/* harness/cli.py:88 — "test": (cmd_test, "Run tests (auto-detects pytest vs unittest)") */}
                    <SectionHeading id="tasks-test" level={2}>
                        test
                    </SectionHeading>
                    <P>
                        Run tests. Auto-detects pytest vs unittest via{' '}
                        <Code>[tool.pytest.*]</Code>, <Code>pytest.ini</Code>,{' '}
                        <Code>&lt;test_dir&gt;/conftest.py</Code>, or a pytest import check — see{' '}
                        README auto-detection rules for details.
                    </P>
                    <CodeBlock lang="bash">{`harness test`}</CodeBlock>

                    {/* harness/cli.py:92-95 — "acceptance": (cmd_acceptance, "Gherkin acceptance tests (pytest-bdd default; behave auto-detected)") */}
                    <SectionHeading id="tasks-acceptance" level={2}>
                        acceptance
                    </SectionHeading>
                    <P>
                        Run Gherkin scenarios. Defaults to pytest-bdd and shares coverage with{' '}
                        <Code>harness test</Code>. Falls back to behave when{' '}
                        <Code>features/steps/</Code> + <Code>features/environment.py</Code> are
                        present or <Code>acceptance_runner = "behave"</Code>. No-ops silently when
                        no <Code>features/</Code> directory exists. See the{' '}
                        <a href="#acceptance">Acceptance section</a> for the full flow.
                    </P>
                    <CodeBlock lang="bash">{`harness acceptance`}</CodeBlock>

                    {/* harness/cli.py:96-99 — "init-acceptance": (cmd_init_acceptance, "Scaffold tests/features + tests/step_defs (pytest-bdd layout)") */}
                    <SectionHeading id="tasks-init-acceptance" level={2}>
                        init-acceptance
                    </SectionHeading>
                    <P>
                        Scaffold a working pytest-bdd example:{' '}
                        <Code>tests/features/example.feature</Code>,{' '}
                        <Code>tests/step_defs/test_example.py</Code>, and{' '}
                        <Code>tests/step_defs/conftest.py</Code>. Refuses to overwrite existing
                        files.
                    </P>
                    <CodeBlock lang="bash">{`harness init-acceptance`}</CodeBlock>

                    {/* harness/cli.py:89 — "audit": (cmd_audit, "Audit dependencies for known vulnerabilities") */}
                    <SectionHeading id="tasks-audit" level={2}>
                        audit
                    </SectionHeading>
                    <P>Audit installed dependencies for known CVEs via pip-audit.</P>
                    <CodeBlock lang="bash">{`harness audit`}</CodeBlock>

                    {/* harness/cli.py:90 — "deps": (cmd_deps, "Dep hygiene: unused/missing/transitive (deptry)") */}
                    <SectionHeading id="tasks-deps" level={2}>
                        deps
                    </SectionHeading>
                    <P>
                        Dependency hygiene via deptry — flags unused, missing, and transitive
                        imports. Auto-passes <Code>--known-first-party</Code> from{' '}
                        <Code>src_dir</Code>. Override with <Code>[tool.deptry]</Code> in{' '}
                        <Code>pyproject.toml</Code>.
                    </P>
                    <CodeBlock lang="bash">{`harness deps`}</CodeBlock>

                    {/* harness/cli.py:91 — "arch": (cmd_arch, "Architectural contracts (import-linter; default: src ↛ tests)") */}
                    <SectionHeading id="tasks-arch" level={2}>
                        arch
                    </SectionHeading>
                    <P>
                        Architectural contracts via import-linter. Uses{' '}
                        <Code>[tool.importlinter]</Code> when present; otherwise runs the bundled
                        default contract forbidding <Code>src_dir</Code> from importing{' '}
                        <Code>test_dir</Code>. Skips with a nudge if <Code>test_dir</Code>{' '}
                        isn&apos;t a Python package.
                    </P>
                    <CodeBlock lang="bash">{`harness arch`}</CodeBlock>

                    {/* harness/cli.py:100 — "coverage": (cmd_coverage, "Tests with coverage threshold (--min=N)")
                        harness/tasks/coverage.py:25 — arg_value("--min=", str(cfg.coverage_min)) */}
                    <SectionHeading id="tasks-coverage" level={2}>
                        coverage
                    </SectionHeading>
                    <P>
                        Run tests with coverage and fail under the configured threshold.{' '}
                        <Code>--min=N</Code> overrides <Code>coverage_min</Code> from config.
                    </P>
                    <CodeBlock lang="bash">{`harness coverage
harness coverage --min=0      # advisory run, never fails
harness coverage --min=85     # override the configured threshold`}</CodeBlock>

                    {/* harness/cli.py:101 — "crap": (cmd_crap, "CRAP complexity x coverage gate")
                        harness/tasks/crap.py:97 — arg_value("--max=", str(cfg.crap_max))
                        harness/tasks/crap.py:98 — "--changed-only" in sys.argv */}
                    <SectionHeading id="tasks-crap" level={2}>
                        crap
                    </SectionHeading>
                    <P>
                        CRAP (Change Risk Anti-Pattern) gate — complexity × coverage per function.{' '}
                        <Code>--max=N</Code> overrides <Code>crap_max</Code>;{' '}
                        <Code>--changed-only</Code> restricts the gate to files changed vs the main
                        branch. Blocking by default; set <Code>enforce_crap = false</Code> to stay
                        advisory.
                    </P>
                    <CodeBlock lang="bash">{`harness crap
harness crap --max=30
harness crap --changed-only   # only fail on functions in changed files`}</CodeBlock>

                    {/* harness/cli.py:102-105 — "mutation": (cmd_mutation, "Mutation testing via mutmut (advisory; see `harness nightly`)")
                        harness/tasks/mutation.py:94  — arg_value("--min-coverage=", str(cfg.mutation_min_coverage))
                        harness/tasks/mutation.py:104 — arg_value("--max-runtime=", str(cfg.mutation_max_runtime))
                        harness/tasks/mutation.py:105 — arg_value("--min-score=", "") */}
                    <SectionHeading id="tasks-mutation" level={2}>
                        mutation
                    </SectionHeading>
                    <P>
                        Mutation testing via mutmut. <Code>--min-coverage=</Code> sets the minimum
                        suite coverage before mutation runs at all,{' '}
                        <Code>--max-runtime=</Code> sets the SIGTERM timeout in seconds, and{' '}
                        <Code>--min-score=</Code> enables blocking mode with the given kill-ratio
                        threshold. Advisory by default unless <Code>enforce_mutation = true</Code>{' '}
                        or <Code>--min-score=</Code> is passed.
                    </P>
                    <CodeBlock lang="bash">{`harness mutation
harness mutation --min-coverage=70 --max-runtime=600
harness mutation --min-score=80            # blocking: fail if kill ratio < 80%
harness mutation --changed-only            # only mutate changed files`}</CodeBlock>

                    {/* harness/cli.py:117 — "clean": (cmd_clean, "Remove cache and build artifacts") */}
                    <SectionHeading id="tasks-clean" level={2}>
                        clean
                    </SectionHeading>
                    <P>Remove caches, build artifacts, and mutation state.</P>
                    <CodeBlock lang="bash">{`harness clean`}</CodeBlock>

                    {/* harness/cli.py:116 — "setup-hooks": (cmd_hooks, "Install git pre-commit and Claude Stop hooks") */}
                    <SectionHeading id="tasks-setup-hooks" level={2}>
                        setup-hooks
                    </SectionHeading>
                    <P>
                        Install the git pre-commit hook and the Claude Code Stop hook. See the{' '}
                        <a href="#hooks">Hooks deep-dive</a> for exactly what gets written.
                    </P>
                    <CodeBlock lang="bash">{`harness setup-hooks`}</CodeBlock>

                    {/* harness/cli.py:123 — "help": (cmd_help, "Show this help message")
                        harness/cli.py:47-77  — _print_detected_block() prints detected paths + thresholds */}
                    <SectionHeading id="tasks-help" level={2}>
                        help
                    </SectionHeading>
                    <P>
                        Print the task list plus detected paths (project root, src/test dirs, test
                        runner, invoker, features dir, acceptance runner) and every active
                        threshold.
                    </P>
                    <CodeBlock lang="bash">{`harness help`}</CodeBlock>
                </>
            ),
            aside: (
                <P>
                    Task list: <Code>harness/cli.py:80-126</Code>. Reach for individual tasks only
                    when debugging — for day-to-day use run a stage (<Code>check</Code>,{' '}
                    <Code>pre-commit</Code>, <Code>ci</Code>, or <Code>nightly</Code>).
                </P>
            ),
        },

        /* ── Configuration — 19-key table ───────────────────────────────────
           Source: /Users/juan/Code/pyharness/CLAUDE.md:34-61 (full [tool.harness] block). */
        {
            content: (
                <>
                    <SectionHeading id="config" level={1}>
                        Configuration — [tool.harness]
                    </SectionHeading>
                    <P>
                        Every key is optional. Unset keys fall through the{' '}
                        <a href="#precedence">precedence cascade</a> to user-global config, then
                        bundled defaults. Drop this block into <Code>pyproject.toml</Code>:
                    </P>
                    {/* CLAUDE.md:34-61 — full annotated [tool.harness] sample block */}
                    <CodeBlock lang="toml">{`[tool.harness]
# Paths / runners
src_dir = "harness"
test_dir = "tests"
test_runner = "pytest"           # "pytest" | "unittest"
test_invoker = "python"          # "python" | "uv"
pytest_args = ["-q"]

# Thresholds — single source of truth for every gate
coverage_min = 80
crap_max = 30.0
complexity_max_ccn = 15
complexity_max_args = 7
complexity_max_loc = 100
mutation_min_coverage = 70.0
mutation_max_runtime = 600
mutation_min_score = 80.0

# Gate enforcement
enforce_crap = true
run_mutation_in_ci = false
enforce_mutation = false

# Acceptance
acceptance_runner = "pytest-bdd" # "pytest-bdd" | "behave" | "off"
features_dir = "tests/features"
run_acceptance_in_check = false`}</CodeBlock>

                    <P>
                        The 19 keys, grouped and sourced from{' '}
                        <Code>CLAUDE.md:34-61</Code>:
                    </P>
                    <div
                        className="w-full max-w-full overflow-x-auto"
                        style={{ padding: '8px 0' }}
                    >
                        <table
                            className="w-full"
                            style={{ borderSpacing: 0, borderCollapse: 'collapse' }}
                        >
                            <thead>
                                <tr>
                                    {['Key', 'Type', 'Default', 'Note'].map((h) => (
                                        <th
                                            key={h}
                                            className="text-left"
                                            style={{
                                                padding: '4px 12px 4px 0',
                                                fontSize: 'var(--type-table-size)',
                                                fontFamily: 'var(--font-primary)',
                                                fontWeight: 400,
                                                color: 'var(--text-muted)',
                                                borderBottom: '1px solid var(--page-border)',
                                            }}
                                        >
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {(
                                    [
                                        // CLAUDE.md:37 — src_dir = "harness"  (auto-detected when unset)
                                        [
                                            'src_dir',
                                            'str',
                                            'auto',
                                            'src/<pkg>, top-level pkg, or [tool.uv.build-backend]',
                                        ],
                                        // CLAUDE.md:38 — test_dir = "tests"
                                        [
                                            'test_dir',
                                            'str',
                                            'auto',
                                            'first existing of tests/, test/, src/tests/',
                                        ],
                                        // CLAUDE.md:39 — test_runner = "pytest"
                                        [
                                            'test_runner',
                                            '"pytest" | "unittest"',
                                            'auto',
                                            'from pytest config / deps / import probe',
                                        ],
                                        // CLAUDE.md:40 — test_invoker = "python"
                                        [
                                            'test_invoker',
                                            '"python" | "uv"',
                                            'auto',
                                            '"uv" when uv.lock is present',
                                        ],
                                        // CLAUDE.md:41 — pytest_args = ["-q"]
                                        [
                                            'pytest_args',
                                            'list[str]',
                                            '[]',
                                            'appended to every pytest invocation',
                                        ],
                                        // CLAUDE.md:44 — coverage_min = 80
                                        [
                                            'coverage_min',
                                            'int',
                                            '80',
                                            'harness coverage fail-under',
                                        ],
                                        // CLAUDE.md:45 — crap_max = 30.0
                                        [
                                            'crap_max',
                                            'float',
                                            '30.0',
                                            'CRAP ceiling (blocking by default)',
                                        ],
                                        // CLAUDE.md:46 — complexity_max_ccn = 15
                                        [
                                            'complexity_max_ccn',
                                            'int',
                                            '15',
                                            'lizard cyclomatic complexity cap',
                                        ],
                                        // CLAUDE.md:47 — complexity_max_args = 7
                                        [
                                            'complexity_max_args',
                                            'int',
                                            '7',
                                            'lizard argument count cap',
                                        ],
                                        // CLAUDE.md:48 — complexity_max_loc = 100
                                        [
                                            'complexity_max_loc',
                                            'int',
                                            '100',
                                            'lizard LOC-per-function cap',
                                        ],
                                        // CLAUDE.md:49 — mutation_min_coverage = 70.0
                                        [
                                            'mutation_min_coverage',
                                            'float',
                                            '70.0',
                                            'mutation skipped below this coverage',
                                        ],
                                        // CLAUDE.md:50 — mutation_max_runtime = 600
                                        [
                                            'mutation_max_runtime',
                                            'int',
                                            '600',
                                            'seconds before mutmut SIGTERM',
                                        ],
                                        // CLAUDE.md:51 — mutation_min_score = 80.0
                                        [
                                            'mutation_min_score',
                                            'float',
                                            '80.0',
                                            'kill-ratio % enforced when blocking',
                                        ],
                                        // CLAUDE.md:54 — enforce_crap = true
                                        [
                                            'enforce_crap',
                                            'bool',
                                            'true',
                                            'false = advisory (old behaviour)',
                                        ],
                                        // CLAUDE.md:55 — run_mutation_in_ci = false
                                        [
                                            'run_mutation_in_ci',
                                            'bool',
                                            'false',
                                            'true = include mutation in harness ci',
                                        ],
                                        // CLAUDE.md:56 — enforce_mutation = false
                                        [
                                            'enforce_mutation',
                                            'bool',
                                            'false',
                                            'true = fail when score < mutation_min_score',
                                        ],
                                        // CLAUDE.md:59 — acceptance_runner = "pytest-bdd"
                                        [
                                            'acceptance_runner',
                                            '"pytest-bdd" | "behave" | "off"',
                                            'auto',
                                            'explicit override for runner detection',
                                        ],
                                        // CLAUDE.md:60 — features_dir = "tests/features"
                                        [
                                            'features_dir',
                                            'str',
                                            'auto',
                                            'tests/features/, features/, or <test_dir>/features/',
                                        ],
                                        // CLAUDE.md:61 — run_acceptance_in_check = false
                                        [
                                            'run_acceptance_in_check',
                                            'bool',
                                            'false',
                                            'true = run scenarios inside harness check',
                                        ],
                                    ] as Array<[string, string, string, string]>
                                ).map(([key, type, def, note]) => (
                                    <tr key={key}>
                                        <td
                                            style={{
                                                padding: '4px 12px 4px 0',
                                                fontSize: 'var(--type-table-size)',
                                                fontFamily: 'var(--font-code)',
                                                fontWeight: 475,
                                                color: 'var(--text-primary)',
                                                borderBottom: '1px solid var(--page-border)',
                                                whiteSpace: 'nowrap',
                                            }}
                                        >
                                            {key}
                                        </td>
                                        <td
                                            style={{
                                                padding: '4px 12px 4px 0',
                                                fontSize: 'var(--type-table-size)',
                                                fontFamily: 'var(--font-code)',
                                                fontWeight: 475,
                                                color: 'var(--text-primary)',
                                                borderBottom: '1px solid var(--page-border)',
                                                whiteSpace: 'nowrap',
                                            }}
                                        >
                                            {type}
                                        </td>
                                        <td
                                            style={{
                                                padding: '4px 12px 4px 0',
                                                fontSize: 'var(--type-table-size)',
                                                fontFamily: 'var(--font-code)',
                                                fontWeight: 475,
                                                color: 'var(--text-primary)',
                                                borderBottom: '1px solid var(--page-border)',
                                                whiteSpace: 'nowrap',
                                            }}
                                        >
                                            {def}
                                        </td>
                                        <td
                                            style={{
                                                padding: '4px 12px 4px 0',
                                                fontSize: 'var(--type-table-size)',
                                                fontFamily: 'var(--font-primary)',
                                                fontWeight: 475,
                                                color: 'var(--text-primary)',
                                                borderBottom: '1px solid var(--page-border)',
                                            }}
                                        >
                                            {note}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            ),
            aside: (
                <P>
                    All 19 keys listed in <Code>CLAUDE.md:34-61</Code> and the expanded discussion
                    in <Code>README.md:85-115</Code>. Run <Code>harness help</Code> to see which
                    values resolved in your project.
                </P>
            ),
        },

        /* ── Precedence cascade ─────────────────────────────────────────────
           Source: /Users/juan/Code/pyharness/README.md:119-124. */
        {
            content: (
                <>
                    <SectionHeading id="precedence" level={1}>
                        Precedence Cascade
                    </SectionHeading>
                    <P>
                        Four layers. Highest wins. This is the contract for every threshold and
                        path pyharness reads.
                    </P>
                    {/* README.md:121 — 1. CLI flags (--min=, --max=, --max-runtime=, --min-score=) */}
                    {/* README.md:122 — 2. Project [tool.harness] in nearest pyproject.toml */}
                    {/* README.md:123 — 3. User-global ~/.config/harness/config.toml (XDG_CONFIG_HOME) */}
                    {/* README.md:124 — 4. Bundled defaults (values in CLAUDE.md + harness/defaults/) */}
                    <List>
                        <Li>
                            <strong>1. CLI flags</strong> — <Code>--min=</Code>,{' '}
                            <Code>--max=</Code>, <Code>--max-runtime=</Code>,{' '}
                            <Code>--min-score=</Code>, <Code>--min-coverage=</Code>. Always win.
                        </Li>
                        <Li>
                            <strong>2. Project config</strong> —{' '}
                            <Code>[tool.harness]</Code> in the nearest <Code>pyproject.toml</Code>{' '}
                            (walked up from CWD, pytest rootdir rules).
                        </Li>
                        <Li>
                            <strong>3. User-global config</strong> —{' '}
                            <Code>~/.config/harness/config.toml</Code> (respects{' '}
                            <Code>$XDG_CONFIG_HOME</Code>). Same keys as{' '}
                            <Code>[tool.harness]</Code>, no wrapper.
                        </Li>
                        <Li>
                            <strong>4. Bundled defaults</strong> — the values shown in the{' '}
                            <a href="#config">config table</a>, plus tool configs under{' '}
                            <Code>harness/defaults/</Code> (see next section).
                        </Li>
                    </List>

                    <P>Example user-global override:</P>
                    {/* README.md:127-131 — ~/.config/harness/config.toml example */}
                    <CodeBlock lang="toml">{`# ~/.config/harness/config.toml  (or $XDG_CONFIG_HOME/harness/config.toml)
coverage_min = 85
crap_max = 25.0`}</CodeBlock>
                </>
            ),
            aside: (
                <P>
                    Precedence contract: <Code>README.md:119-124</Code>. Same rules apply to every
                    threshold — there is no second cascade for special cases.
                </P>
            ),
        },

        /* ── Bundled defaults ───────────────────────────────────────────────
           Source: /Users/juan/Code/pyharness/README.md:133-145
                 + ls /Users/juan/Code/pyharness/harness/defaults/:
             ruff.toml, pyrightconfig.json, coveragerc,
             importlinter_template.ini, bdd_example.feature,
             bdd_test_example.py, bdd_conftest.py. */
        {
            content: (
                <>
                    <SectionHeading id="defaults" level={1}>
                        Bundled Defaults — harness/defaults/
                    </SectionHeading>
                    <P>
                        When the target project has no config for a given tool, pyharness injects
                        its bundled default. This is why <Code>harness lint</Code>,{' '}
                        <Code>harness typecheck</Code>, <Code>harness coverage</Code>, and{' '}
                        <Code>harness arch</Code> work in a brand-new repo with zero setup. When a
                        project declares its own config (or a sidecar like{' '}
                        <Code>ruff.toml</Code>/<Code>.coveragerc</Code>/
                        <Code>pyrightconfig.json</Code>/<Code>.importlinter</Code>), the bundled
                        default is skipped.
                    </P>

                    <div
                        className="w-full max-w-full overflow-x-auto"
                        style={{ padding: '8px 0' }}
                    >
                        <table
                            className="w-full"
                            style={{ borderSpacing: 0, borderCollapse: 'collapse' }}
                        >
                            <thead>
                                <tr>
                                    {['File', 'Tool', 'Injected when'].map((h) => (
                                        <th
                                            key={h}
                                            className="text-left"
                                            style={{
                                                padding: '4px 12px 4px 0',
                                                fontSize: 'var(--type-table-size)',
                                                fontFamily: 'var(--font-primary)',
                                                fontWeight: 400,
                                                color: 'var(--text-muted)',
                                                borderBottom: '1px solid var(--page-border)',
                                            }}
                                        >
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {(
                                    [
                                        // README.md:139 — ruff.toml fallback, injected as --config
                                        [
                                            'harness/defaults/ruff.toml',
                                            'ruff (lint / fix / format / format-check)',
                                            'no [tool.ruff] or ruff.toml / .ruff.toml',
                                        ],
                                        // README.md:140 — pyrightconfig.json fallback, injected as --project
                                        [
                                            'harness/defaults/pyrightconfig.json',
                                            'basedpyright (typecheck)',
                                            'no [tool.basedpyright] or pyrightconfig.{json,toml}',
                                        ],
                                        // README.md:141 — coveragerc fallback, injected as --rcfile=
                                        [
                                            'harness/defaults/coveragerc',
                                            'coverage.py (coverage)',
                                            'no [tool.coverage.*] or .coveragerc',
                                        ],
                                        // README.md:142 — importlinter_template.ini fallback (default contract: src ↛ tests)
                                        [
                                            'harness/defaults/importlinter_template.ini',
                                            'import-linter (arch)',
                                            'no [tool.importlinter] / .importlinter / setup.cfg',
                                        ],
                                        // ls harness/defaults/ — bdd_example.feature (copied by init-acceptance)
                                        [
                                            'harness/defaults/bdd_example.feature',
                                            'pytest-bdd (init-acceptance)',
                                            'always — seed file for scaffolded scenario',
                                        ],
                                        // ls harness/defaults/ — bdd_test_example.py
                                        [
                                            'harness/defaults/bdd_test_example.py',
                                            'pytest-bdd (init-acceptance)',
                                            'always — seed step definitions',
                                        ],
                                        // ls harness/defaults/ — bdd_conftest.py
                                        [
                                            'harness/defaults/bdd_conftest.py',
                                            'pytest-bdd (init-acceptance)',
                                            'always — shared fixtures stub',
                                        ],
                                    ] as Array<[string, string, string]>
                                ).map(([file, tool, when]) => (
                                    <tr key={file}>
                                        <td
                                            style={{
                                                padding: '4px 12px 4px 0',
                                                fontSize: 'var(--type-table-size)',
                                                fontFamily: 'var(--font-code)',
                                                fontWeight: 475,
                                                color: 'var(--text-primary)',
                                                borderBottom: '1px solid var(--page-border)',
                                                whiteSpace: 'nowrap',
                                            }}
                                        >
                                            {file}
                                        </td>
                                        <td
                                            style={{
                                                padding: '4px 12px 4px 0',
                                                fontSize: 'var(--type-table-size)',
                                                fontFamily: 'var(--font-primary)',
                                                fontWeight: 475,
                                                color: 'var(--text-primary)',
                                                borderBottom: '1px solid var(--page-border)',
                                            }}
                                        >
                                            {tool}
                                        </td>
                                        <td
                                            style={{
                                                padding: '4px 12px 4px 0',
                                                fontSize: 'var(--type-table-size)',
                                                fontFamily: 'var(--font-primary)',
                                                fontWeight: 475,
                                                color: 'var(--text-primary)',
                                                borderBottom: '1px solid var(--page-border)',
                                            }}
                                        >
                                            {when}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    {/* README.md:143 — deps: no bundled fallback, deptry built-ins apply */}
                    {/* README.md:144 — mutation: no bundled fallback, mutmut reads pyproject.toml */}
                    <P>
                        Two tasks ship no bundled fallback: <Code>deps</Code> relies on deptry&apos;s
                        built-ins, and <Code>mutation</Code> reads mutmut&apos;s own{' '}
                        <Code>pyproject.toml</Code> entry.
                    </P>
                </>
            ),
            aside: (
                <P>
                    Fallback table: <Code>README.md:133-145</Code>. Directory listing:{' '}
                    <Code>harness/defaults/</Code>. Each file is shipped inside the installed
                    wheel — no network fetch.
                </P>
            ),
        },

        /* ── Acceptance deep-dive ───────────────────────────────────────────
           Seeds quoted verbatim from
           /Users/juan/Code/pyharness/harness/defaults/bdd_example.feature
           and /Users/juan/Code/pyharness/harness/defaults/bdd_test_example.py. */
        {
            content: (
                <>
                    <SectionHeading id="acceptance" level={1}>
                        Acceptance (Gherkin)
                    </SectionHeading>
                    <P>
                        <Code>harness init-acceptance</Code> scaffolds three files (refuses to
                        overwrite existing ones). <Code>harness acceptance</Code> then runs them —
                        pytest-bdd by default, behave when a behave layout is detected, or off when
                        <Code> acceptance_runner = &quot;off&quot;</Code>.
                    </P>

                    <P>
                        <strong>Seed 1 —</strong>{' '}
                        <Code>harness/defaults/bdd_example.feature</Code>:
                    </P>
                    {/* Verbatim from harness/defaults/bdd_example.feature (read file confirmed). */}
                    <CodeBlock lang="gherkin">{`Feature: Example acceptance scenario
  As a new project
  I want one runnable Gherkin scenario
  So that \`harness acceptance\` has something to execute

  Scenario: Arithmetic sanity
    Given the number 2
    When I add 3
    Then the result is 5`}</CodeBlock>

                    <P>
                        <strong>Seed 2 —</strong>{' '}
                        <Code>harness/defaults/bdd_test_example.py</Code>:
                    </P>
                    {/* Verbatim from harness/defaults/bdd_test_example.py (read file confirmed). */}
                    <CodeBlock lang="python">{`"""Step definitions for the scaffolded example feature."""

from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/example.feature")


@given(parsers.parse("the number {value:d}"), target_fixture="value")
def _value(value: int) -> int:
    return value


@when(parsers.parse("I add {addend:d}"), target_fixture="result")
def _add(value: int, addend: int) -> int:
    return value + addend


@then(parsers.parse("the result is {expected:d}"))
def _check(result: int, expected: int) -> None:
    assert result == expected  # noqa: S101`}</CodeBlock>

                    <P>
                        A third file, <Code>harness/defaults/bdd_conftest.py</Code>, is copied to{' '}
                        <Code>tests/step_defs/conftest.py</Code> as a stub for shared fixtures.
                    </P>

                    {/* README.md:66-70 — runner detection order */}
                    <P>
                        <strong>Runner detection order</strong> (from{' '}
                        <Code>README.md:66-70</Code>):
                    </P>
                    <List>
                        <Li>
                            <Code>acceptance_runner</Code> in config (
                            <Code>&quot;pytest-bdd&quot;</Code> | <Code>&quot;behave&quot;</Code> |{' '}
                            <Code>&quot;off&quot;</Code>) — explicit override.
                        </Li>
                        <Li>
                            Behave layout detected:{' '}
                            <Code>features_dir/steps/</Code> +{' '}
                            <Code>features_dir/environment.py</Code> → behave.
                        </Li>
                        <Li>
                            <Code>behave</Code> declared as a dependency but{' '}
                            <Code>pytest-bdd</Code> not → behave.
                        </Li>
                        <Li>Default → pytest-bdd.</Li>
                    </List>

                    {/* README.md:72 — ci always runs acceptance when features dir exists;
                        check opts in via run_acceptance_in_check. */}
                    <P>
                        Acceptance always runs in <Code>harness ci</Code> when a features directory
                        exists. It&apos;s opt-in for <Code>harness check</Code> via{' '}
                        <Code>run_acceptance_in_check = true</Code>.
                    </P>
                </>
            ),
            aside: (
                <P>
                    Seeds live at <Code>harness/defaults/bdd_*.{'{'}feature,py{'}'}</Code>. The
                    scaffold target paths — <Code>tests/features/example.feature</Code>,{' '}
                    <Code>tests/step_defs/test_example.py</Code>,{' '}
                    <Code>tests/step_defs/conftest.py</Code> — are fixed per{' '}
                    <Code>CLAUDE.md:24</Code>.
                </P>
            ),
        },

        /* ── Hooks deep-dive ────────────────────────────────────────────────
           Source: /Users/juan/Code/pyharness/README.md:149-159
                 + /Users/juan/Code/pyharness/harness/stages/setup_hooks.py. */
        {
            content: (
                <>
                    <SectionHeading id="hooks" level={1}>
                        Hooks Deep-Dive — harness setup-hooks
                    </SectionHeading>
                    <P>
                        One command, two hooks. Both reference the exact Python interpreter that
                        installed pyharness, so they survive venv changes.
                    </P>
                    <CodeBlock lang="bash">{`harness setup-hooks`}</CodeBlock>

                    {/* README.md:156 — .git/hooks/pre-commit runs harness pre-commit
                        harness/stages/setup_hooks.py:62-66 — writes hook file, chmod 0o755 */}
                    <SectionHeading id="hooks-pre-commit" level={2}>
                        Git pre-commit hook
                    </SectionHeading>
                    <P>
                        Writes <Code>.git/hooks/pre-commit</Code> — a one-line shell wrapper that
                        execs <Code>harness pre-commit</Code> with the interpreter recorded at
                        install time. The hook file is <Code>chmod 0o755</Code>. Parent directories
                        are created if missing. Skip in an emergency with{' '}
                        <Code>git commit --no-verify</Code>.
                    </P>
                    <CodeBlock lang="bash">{`#!/bin/sh
exec '<python>' -m harness.cli pre-commit`}</CodeBlock>

                    {/* README.md:157 — .claude/settings.json Stop hook runs harness post-edit
                        harness/stages/setup_hooks.py:68-77 — loads JSON, merges, writes back */}
                    <SectionHeading id="hooks-claude" level={2}>
                        Claude Code Stop hook
                    </SectionHeading>
                    <P>
                        Appends a <Code>Stop</Code> hook to{' '}
                        <Code>.claude/settings.json</Code> that runs{' '}
                        <Code>harness post-edit</Code> after Claude Code sessions. That task runs
                        ruff fix + format over the files the session touched — silent no-op when
                        nothing relevant changed.
                    </P>
                    <CodeBlock lang="json">{`{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "<python> -m harness.cli post-edit" }
        ]
      }
    ]
  }
}`}</CodeBlock>

                    {/* harness/stages/setup_hooks.py:13-16 — _is_post_edit_command()
                        harness/stages/setup_hooks.py:19-55 — _ensure_stop_hook() merges existing
                          entries, dedupes any previous post-edit command, appends once. */}
                    <SectionHeading id="hooks-idempotency" level={2}>
                        Idempotency
                    </SectionHeading>
                    <P>
                        Running <Code>harness setup-hooks</Code> repeatedly never duplicates the
                        post-edit hook. <Code>_ensure_stop_hook</Code> walks the existing{' '}
                        <Code>hooks.Stop</Code> list, drops any prior entry whose command ends in{' '}
                        <Code>harness.cli post-edit</Code> (or equals{' '}
                        <Code>uv run harness post-edit</Code>), preserves every other hook the user
                        has configured, and appends the fresh entry once.
                    </P>
                    <P>
                        The git pre-commit hook is overwritten each run — pyharness always owns the
                        contents of <Code>.git/hooks/pre-commit</Code>.
                    </P>
                </>
            ),
            aside: (
                <P>
                    Implementation: <Code>harness/stages/setup_hooks.py</Code>. Summary:{' '}
                    <Code>README.md:149-159</Code>. Reinstall any time you switch venvs — both
                    hooks pick up the new Python path.
                </P>
            ),
        },
    ] as EditorialSection[],
};
