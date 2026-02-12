# AGENTS.md

Project operating guide for Codex in this repository. This file synthesizes standards from `../everything-claude-code` and project-specific workflow decisions.

## 1. Mission

- Build and maintain a high-quality AI writing + MCP workflow for this blog workspace.
- Prioritize clarity, safety, reproducibility, and fast iteration.
- Default to practical implementation over abstract discussion.

## 2. Operating Modes

### Development Mode

- Write code first, explain after.
- Keep diffs focused and atomic.
- Verify changes with tests or direct executable checks.

### Research Mode

- Read broadly before editing.
- Gather evidence from source files.
- Present findings first, then recommendations.

### Review Mode

- Review by severity: `critical > high > medium > low`.
- Focus on bugs, security, regressions, missing tests.
- Provide concrete fixes, not only critique.

## 3. Core Engineering Standards

### Architecture and Code Quality

- Prefer simple, explicit designs over clever abstractions.
- Use small, cohesive modules.
- Target file size around `200-400` lines where practical, avoid very large files.
- Prefer immutable updates over mutating shared state.
- Avoid deep nesting and hidden side effects.
- Validate all external inputs at boundaries.

### Error Handling

- Fail fast with clear messages.
- Never silently swallow errors.
- Log actionable error context without leaking secrets.

### Performance

- Optimize after identifying bottlenecks.
- Avoid unnecessary repeated scans and expensive operations.
- Keep context and token usage lean during long sessions.

## 4. Python Standards (Repository-Relevant)

- Follow PEP 8.
- Add type hints on function signatures.
- Prefer `pytest` for tests.
- Use formatter/linting stack where applicable: `black`, `isort`, `ruff`.
- Use context managers for resource handling.
- Use dataclasses/typed models for structured data where helpful.

## 5. Security Requirements

Before closing any implementation:

- No hardcoded secrets, tokens, keys, or passwords.
- Validate and sanitize user-controlled input.
- Avoid unsafe file/path handling.
- Use parameterized DB operations where relevant.
- Ensure error messages do not leak sensitive internals.
- Review dependency/security risk when adding new packages.

If a security issue is found:

1. Stop and contain risk.
2. Fix critical exposure first.
3. Re-check adjacent code for similar patterns.

## 6. Testing and Verification

- Prefer TDD for non-trivial feature or bug work:
  1. Write failing test.
  2. Implement minimal fix.
  3. Refactor safely.
- Maintain meaningful test coverage (target `80%+` on touched areas when feasible).
- Verify with the smallest reliable command set first, then broader checks as needed.

## 7. Git and Change Hygiene

- Use conventional commit style when committing:
  - `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `ci:`
- Keep commits focused and reviewable.
- Do not mix unrelated refactors with functional changes.
- Summarize behavior impact and verification steps in PR/handoff notes.

## 8. Agent Orchestration Playbook

Use specialized agents (or emulate their behavior if unavailable) for complex tasks:

- `planner`: complex feature planning and decomposition.
- `architect`: system design and trade-off decisions.
- `tdd-guide`: test-first implementation flow.
- `code-reviewer`: mandatory post-change quality review.
- `security-reviewer`: auth/input/secrets/sensitive-data checks.
- `build-error-resolver`: minimal-diff build recovery.
- `e2e-runner`: critical end-to-end journey validation.
- `refactor-cleaner`: dead code and duplication cleanup.
- `doc-updater`: docs and codemap synchronization.
- `python-reviewer`: Python-specific idioms, type and quality checks.
- `database-reviewer`: SQL/schema/index/performance/RLS review.
- `go-reviewer` and `go-build-resolver`: use only for Go work.

Execution guidance:

- Run independent analyses in parallel whenever possible.
- Use multi-perspective review for high-risk changes (architecture, security, performance).

## 9. Skill System

A skill is a local workflow package with `SKILL.md`.

### Installed Skills in This Environment

- `humanizer`
  File: `/home/mike/.codex/skills/humanizer/SKILL.md`
  Use when editing/reviewing prose for natural human tone.

- `skill-creator`
  File: `/home/mike/.codex/skills/.system/skill-creator/SKILL.md`
  Use when designing or updating skills.

- `skill-installer`
  File: `/home/mike/.codex/skills/.system/skill-installer/SKILL.md`
  Use when listing or installing additional skills.

### Reference Skill Catalog (from everything-claude-code)

Complete reference list:

- Core engineering:
  `coding-standards`, `backend-patterns`, `frontend-patterns`, `security-review`, `tdd-workflow`, `verification-loop`, `eval-harness`.
- Workflow and context:
  `iterative-retrieval`, `strategic-compact`, `continuous-learning`, `continuous-learning-v2`, `configure-ecc`, `project-guidelines-example`.
- Python/Django:
  `python-patterns`, `python-testing`, `django-patterns`, `django-security`, `django-tdd`, `django-verification`.
- Go:
  `golang-patterns`, `golang-testing`.
- Java/Spring:
  `java-coding-standards`, `springboot-patterns`, `springboot-security`, `springboot-tdd`, `springboot-verification`, `jpa-patterns`.
- Data and integration:
  `postgres-patterns`, `clickhouse-io`, `nutrient-document-processing`.

### Skill Usage Rules

1. If user names a skill, use it.
2. If task clearly matches a skill, use it proactively.
3. Load only the minimum required skill content.
4. Reuse skill scripts/templates/assets over manual reimplementation.
5. If skill unavailable or blocked, state that and continue with best fallback.

## 10. Command Playbooks (Reference)

Complete reference command list:

- Core: `plan`, `tdd`, `code-review`, `verify`, `test-coverage`, `e2e`, `build-fix`, `refactor-clean`.
- Language-specific: `python-review`, `go-review`, `go-test`, `go-build`.
- Documentation: `update-docs`, `update-codemaps`.
- Learning/evals: `learn`, `checkpoint`, `eval`, `evolve`, `skill-create`, `instinct-status`, `instinct-import`, `instinct-export`, `sessions`.
- Orchestration/ops: `orchestrate`, `multi-plan`, `multi-execute`, `multi-backend`, `multi-frontend`, `multi-workflow`, `pm2`, `setup-pm`.

Use these as workflow patterns even when exact slash commands are not available.

## 11. Project-Specific Blog Workflow (Mandatory)

### Source and Writing Workflow

- When checking blog sources, consult `KB - influencial AI blogs.md` first, then expand to other sources as needed.
- For new blog writing, use:
  - `Prompt - thought partner and blog writer.md`
  - `Brand Voice Profile.md`
- For new idea generation, use:
  - `Prompt - deep post ideas.md`
- For voice profile work, use:
  - `Prompt - my brand architect.md`
  - Save output to `Brand Voice Profile.md`.

### Content Quality Rules

- Always run a final `humanizer` pass before considering a generated blog post complete.
- Avoid duplicate outline themes by checking `Post Outlines/` first.
- Do not regenerate rejected outline theme:
  - "The Isolation Advantage" (networking vs isolation strategy).

## 12. MCP and Environment Notes

- MCP server should run via `uv run` with local cache and dedicated environment in `.vscode/mcp.json`.
- Prefer project-local environment/cache settings to avoid permission/path issues across WSL/Windows boundaries.
- If dependency sync fails due sandbox/network constraints, retry with approved escalation flow.

## 13. Completion Checklist

Before declaring work done:

- Requirements addressed.
- Security sanity check completed.
- Tests/checks run or explicitly noted if not run.
- Documentation/instructions updated if behavior changed.
- Risks, assumptions, and next steps clearly stated.
