# PrivyFlow — Product and Engineering Process

## 1. Roles

| Role | Responsibility |
|---|---|
| Product owner / technical lead | Owns product direction, scope, priorities, acceptance, and architecture approval. |
| AI coding agent | Analyzes requirements, proposes plans, implements approved work, validates, and updates documentation. |
| Reviewer | Reviews correctness, security, maintainability, tests, and architecture compliance. |

## 2. Mandatory workflow

1. **Understand:** Restate the requested outcome, constraints, and assumptions.
2. **Inspect:** Read relevant documentation, source code, tests, and current status.
3. **Assign ownership:** Identify whether the Sanitization or De-sanitization Service owns the change.
4. **Plan:** Define API contracts, data ownership, security controls, files, tests, risks, and acceptance criteria.
5. **Approve:** Ask for approval before material changes to scope, service boundaries, cryptography, or infrastructure.
6. **Define expected behavior:** Write measurable acceptance criteria for the change.
7. **Write tests:** Add tests for that behavior first, in the right suites (`docs/TEST_STRATEGY.md`).
8. **Implement:** Make small, reviewable changes.
9. **Execute tests:** Run relevant tests, migrations, static checks, and manual API verification.
10. **Review results:** Fix failures. Do not weaken or delete tests to pass.
11. **Report:** State changed files, exact commands, actual results, known gaps, and next steps.
12. **Document:** Update `STATUS.md`, `PLAN.md`, and relevant specifications.

## 3. Planning and implementing

Work goes in two steps, with the product owner's review in between.

**Planning.** When asked to plan, as in "Please plan the Sanitization Service foundation", write the plan to `docs/PLAN.md` (or `docs/PLAN_<FEATURE>.md`) and write no code.

- Split the work into phases, each building on the last.
- Say what each phase builds and why that approach was chosen, so the owner can review it.
- Give each phase success criteria you can verify yourself: tests that pass, commands and their output, API calls and their responses. Write each one as a checkbox.
- Then stop and wait until asked to implement the plan.

**Implementing.** When asked to implement the plan, build every phase in order. For each phase:

1. Build it, with tests.
2. Check every success criterion and fix whatever fails.
3. Tick off its criteria in the plan and update `docs/STATUS.md`.
4. Commit. If a commit hook fails, fix the problem and commit again.

When the last phase is done, run the full check suite and report the actual results.

## 4. Rules

- Add tests with each change. Tests never call external services or real models; use stubs.
- Outside a plan, commit each change once it has been checked.
- Run the full check suite (lint, format, types, tests) before handing work over.
- Never use `git commit --no-verify`.
- Never lower a threshold, turn off a rule, or exclude a file to get a green run. If a rule looks wrong, stop and ask.
- Keep `docs/STATUS.md` up to date.
- Never push unless asked.
- Everything must work on Windows.

## 5. Testing, review, and release

### Testing in the workflow

- Tests are written before or with the implementation, never deferred to the end.
- A change is not ready for review until the relevant suites have been run and the results are reported.
- Evidence format: exact command, date, and pass, fail, and skip counts. Pending and skipped tests are listed as such.
- Never claim tests passed unless they were executed.

### Code review

A reviewer approves only when all of the following are true:

- Tests exist for the new behavior, including negative and security cases.
- Test evidence is recorded in `STATUS.md` and CI is green.
- No test was deleted, skipped, or weakened, and no coverage threshold was lowered, without product owner approval.
- Fixtures use synthetic data only; no secrets or real PII are committed.
- Service boundaries and data ownership are preserved.

### Regression testing

- Every fixed defect gets a regression test that fails before the fix.
- The full suite runs in CI on every push and pull request.
- Detection or policy changes re-run the detection evaluation and compare it with the recorded baseline.

### Release approval

A release requires:

1. Every release gate in `docs/TEST_STRATEGY.md` section 15 passes with recorded evidence.
2. A clean full regression run, including security, evaluation, end-to-end, and performance checks.
3. Production-readiness validation reviewed: TLS, identity, KMS, monitoring, backups, incident response, and recovery.
4. Explicit approval from the product owner. An agent never releases or deploys on its own.

## 6. Feature planning template

Use `docs/PLAN_<FEATURE>.md` for substantial work.

```markdown
# PLAN_<FEATURE>.md

## Objective

## Scope
### Included
### Excluded

## Service ownership

## API contract

## Data model

## Security and privacy considerations

## Implementation steps

## Files expected to change

## Tests and validation

## Acceptance criteria
- [ ] ...

## Risks and open questions
```

## 7. Change management

- Do not merge the two services.
- Do not give De-sanitization Service direct access to the Sanitization database.
- Do not duplicate the encrypted mapping vault.
- Do not add document extraction, chunking, embeddings, vector databases, RAG, or LLM integration without explicit approval.
- Do not add infrastructure dependencies without a documented need.
- Do not create cloud resources, deploy externally, or incur costs without explicit approval.
- Record material architecture decisions in an ADR.
- Prefer backward-compatible API changes; document breaking changes.

## 8. Definition of done

- Work matches approved scope and service ownership.
- API and data contracts are documented.
- Authorization, tenant isolation, and privacy risks are addressed.
- Tests were written for the behavior, executed, and passed; actual results are reported with evidence.
- Security, negative, and regression tests are included where applicable.
- Migrations are included and validated where applicable.
- No secrets or sensitive payloads are committed or logged.
- Documentation and project status are updated.
- Known limitations and residual risks are recorded.

## 9. Git conventions

- Use focused branches, for example `feature/sanitization-policy-engine`.
- Use imperative commit messages, for example `Add encrypted mapping vault`.
- Keep commits focused.
- Exclude `.env`, keys, credentials, virtual environments, caches, local databases, and sensitive test data.
- Review diffs for secrets and unrelated changes.
