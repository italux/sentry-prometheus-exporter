# Sentry API Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify every Sentry Web API endpoint called from `libs/sentry.py` against Sentry's current API documentation, record a verdict for each, and — where the docs point to a replacement — support the new endpoint without breaking existing deployments. Closes GitHub issue [#114](https://github.com/italux/sentry-prometheus-exporter/issues/114).

**Architecture:** No test suite exists in this repo today. First add a minimal `pytest` + `responses` characterization-test harness that pins the exact URL each `SentryAPI` method currently calls, plus a Docker-based way to run that suite locally so it doesn't depend on the contributor's local Python setup. Then, for each endpoint group, fetch the relevant page at https://docs.sentry.io/api/, compare it against the pinned URL, and record the finding in `docs/sentry-api-audit.md`. If an endpoint is confirmed deprecated, the code keeps calling the current (legacy) URL by default and only switches to the new one when a new env var (`SENTRY_USE_LEGACY_API`) opts in — so no existing deployment's behavior changes just from upgrading.

**Tech Stack:** Python 3, `requests`, `pytest`, `responses` (HTTP mocking for `requests`), Docker/docker-compose (already used by this repo).

## Global Constraints

- Base this audit on `master` **after** PRs #82, #70, #53, and #20 are merged (all four are approved) — line references below assume that merged state. #53 changes `project_stats()` and #20 changes issue/environment handling that this audit's tasks touch.
- PR #58 stays out of scope for merging (still pending its yield-loop fix and its own `eventsv2`→`events` rework per the existing review comment) — don't re-verify `eventsv2` here, that finding is already confirmed and tracked on #58.
- Source of truth is https://docs.sentry.io/api/ as fetched during this work, not prior memory/assumptions — every row in the audit doc must cite the docs page it was checked against.
- **No breaking changes.** Every endpoint migration this audit makes must be opt-in via the `SENTRY_USE_LEGACY_API` env var, defaulting to `"True"` (today's behavior). Existing `requirements.txt`, `Dockerfile` production image/stage, `docker-compose.yaml` service ports/names, and all current env vars stay exactly as they work today.
- No endpoint gets modified without a corresponding pin-test update in the same task, so `pytest` stays green throughout.
- Nothing gets committed or pushed to the remote, and nothing gets posted to issue #114, without the user's explicit go-ahead in that turn — work stays local until asked for. (Local `git commit`s inside this worktree are fine and expected per-task; `git push` and `gh` publish commands are not to be run by an implementer or reviewer under any circumstance.)

## Backward-compatible migration mechanism

Add one new constructor parameter to `SentryAPI` in `libs/sentry.py`:

```python
def __init__(self, base_url, auth_token, use_legacy_api=True):
    ...
    self.use_legacy_api = use_legacy_api
```

Wire it from a new env var in `exporter.py`, following the existing `getenv(...)` / `"True"`/`"False"` string convention already used for other feature toggles in this codebase:

```python
SENTRY_USE_LEGACY_API = getenv("SENTRY_USE_LEGACY_API", "True")
sentry = SentryAPI(SENTRY_BASE_URL, SENTRY_TOKEN, use_legacy_api=(SENTRY_USE_LEGACY_API == "True"))
```

Default `"True"` — every existing deployment keeps hitting the exact URLs it hits today after upgrading, zero action required. Only methods where the audit finds a deprecated endpoint gain a branch:

```python
if self.use_legacy_api:
    resp = self.__get("projects/{}/{}/issues/".format(org_slug, proj_slug))
else:
    resp = self.__get("organizations/{}/issues/?project={}".format(org_slug, proj_slug))  # example only — real replacement URL comes from the docs check
```

Methods where the audit confirms the current endpoint is still correct get **no branch at all**. Document `SENTRY_USE_LEGACY_API` in `README.md`'s env var section once at least one method uses it.

## File Structure

- Create: `requirements-dev.txt` — adds `pytest` and `responses` as dev-only dependencies. Not installed in the production image.
- Create: `tests/__init__.py` and `tests/test_sentry_api_endpoints.py` — one characterization test per `SentryAPI` method, asserting the exact request URL via `responses`, parametrized over `use_legacy_api=True/False` for any method that gains the branch above.
- Create: `docs/sentry-api-audit.md` — the audit findings table (endpoint, method, doc page checked, verdict, action taken, env var if any).
- Modify: `Dockerfile` — multi-stage build: unchanged `base` stage (today's production image, same final `CMD`), plus a new `test` stage built `FROM base` that additionally installs `requirements-dev.txt` and defaults its `CMD` to `pytest`. `docker build .` (no `--target`) keeps producing the exact same image as today.
- Modify: `docker-compose.yaml` — add a new `tests` service (`build: {context: ., target: test}`, no ports, `command: pytest -v`) alongside the existing `prometheus`/`grafana`/`sentry-exporter` services, none of which are touched.
- Modify: `libs/sentry.py` — only where docs confirm a change is needed (via the `use_legacy_api` branch above), plus one already-known bug fix (Task 4) that ships unconditionally.
- Modify: `exporter.py` — thread `SENTRY_USE_LEGACY_API` through to `SentryAPI(...)` construction.
- Modify: `README.md` — document `SENTRY_USE_LEGACY_API` and the "Running tests locally" section.

---

### Task 1: Test harness + Docker test runner + audit doc skeleton

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py`
- Create: `tests/test_sentry_api_endpoints.py`
- Create: `docs/sentry-api-audit.md`
- Modify: `Dockerfile`
- Modify: `docker-compose.yaml`
- Modify: `README.md`

**Interfaces:**
- Produces: a `sentry_api` pytest fixture (in `tests/test_sentry_api_endpoints.py`) that later tasks' tests import and reuse — `SentryAPI(base_url="https://sentry.example.com/api/0/", auth_token="test-token")`.
- Produces: `docs/sentry-api-audit.md` with a Markdown table header that later tasks append rows to.
- Produces: a `test` Docker build stage and a `tests` compose service that later tasks' local runs can use (`docker compose run --rm tests`).

- [ ] **Step 1: Add dev dependencies**

```
# requirements-dev.txt
-r requirements.txt
pytest==8.3.4
responses==0.25.3
```

- [ ] **Step 2: Install and verify pytest runs with zero tests**

Run: `pip install -r requirements-dev.txt && pytest --collect-only`
Expected: exits 0, reports "no tests collected" (no test files exist yet).

- [ ] **Step 3: Create the shared fixture**

```python
# tests/__init__.py
```

```python
# tests/test_sentry_api_endpoints.py
import pytest
import responses

from libs.sentry import SentryAPI

BASE_URL = "https://sentry.example.com/api/0/"


@pytest.fixture
def sentry_api():
    return SentryAPI(base_url=BASE_URL, auth_token="test-token")
```

- [ ] **Step 4: Run pytest to confirm the fixture file collects cleanly**

Run: `pytest --collect-only`
Expected: exits 0, still "no tests collected" (fixture alone isn't a test).

- [ ] **Step 5: Create the audit doc skeleton**

```markdown
# Sentry API Audit

Tracks issue #114 — verifying every endpoint `libs/sentry.py` calls against
Sentry's current API docs (https://docs.sentry.io/api/).

| SentryAPI method | Endpoint (as called today) | Docs page checked | Verdict | Action | Env var |
|---|---|---|---|---|---|
```

- [ ] **Step 6: Convert `Dockerfile` to a multi-stage build**

Replace the current single-stage `Dockerfile` with:

```dockerfile
FROM python:3.7-slim AS base
LABEL maintainer="Italo Santos <italux.santos@gmail.com>"
LABEL description="Sentry Issues & Events Exporter"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY helpers/ /app/helpers/
COPY libs/ /app/libs/
COPY exporter.py /app/

USER nobody

# The binding port was picked from the Default port allocations documentation:
# https://github.com/prometheus/prometheus/wiki/Default-port-allocations
EXPOSE 9790
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:9790", "exporter:app"]

FROM base AS test
USER root
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ /app/tests/
USER nobody
CMD ["pytest", "-v"]
```

`base` is unchanged from today's production image (same layers, same final `CMD`), and it remains the last stage built when `docker build .` is run without `--target` — so the default production build is byte-for-byte the same as before this task.

- [ ] **Step 7: Verify both Docker targets build and run**

Run: `docker build -t sentry-prometheus-exporter:audit-base .`
Expected: succeeds; `docker run --rm sentry-prometheus-exporter:audit-base gunicorn --version` prints a version (production image still works).

Run: `docker build --target test -t sentry-prometheus-exporter:audit-test .`
Expected: succeeds; `docker run --rm sentry-prometheus-exporter:audit-test` runs pytest and exits 0 (no tests collected yet, but the runner works end to end).

- [ ] **Step 8: Add the `tests` service to `docker-compose.yaml`**

Add alongside the existing `prometheus`, `grafana`, and `sentry-exporter` services (none of which are touched):

```yaml
  tests:
    container_name: "sentry-prometheus-exporter-tests"
    build:
      context: .
      target: test
    command: pytest -v
```

- [ ] **Step 9: Verify the compose test runner**

Run: `docker compose run --rm tests`
Expected: exits 0, "no tests collected" (same as Step 7's direct `docker run`, now via compose).

- [ ] **Step 10: Document local testing in `README.md`**

Add a "Running tests locally" section documenting `docker compose run --rm tests` as the primary path, with `pip install -r requirements-dev.txt && pytest` as the no-Docker alternative.

- [ ] **Step 11: Commit**

```bash
git add requirements-dev.txt tests/__init__.py tests/test_sentry_api_endpoints.py docs/sentry-api-audit.md Dockerfile docker-compose.yaml README.md
git commit -m "test: add pytest+responses harness, Docker test runner, and audit doc skeleton for #114"
```

---

### Task 2: Verify organizations & projects endpoints

**Files:**
- Modify: `tests/test_sentry_api_endpoints.py`
- Modify: `docs/sentry-api-audit.md`
- Modify (only if docs require it): `libs/sentry.py`, `README.md`

**Interfaces:**
- Consumes: `sentry_api` fixture and `BASE_URL` from Task 1.
- Covers: `SentryAPI.organizations()` → `GET organizations/`, `SentryAPI.projects(org_slug)` → `GET organizations/{org}/projects/?all_projects=1`, `SentryAPI.project(org_slug, proj_slug)` → `GET projects/{org}/{proj_slug}/`.

- [ ] **Step 1: Write the pin tests (pass against today's behavior)**

```python
@responses.activate
def test_organizations_calls_expected_endpoint(sentry_api):
    responses.add(responses.GET, BASE_URL + "organizations/", json=[])
    sentry_api.organizations()
    assert responses.calls[0].request.url == BASE_URL + "organizations/"


@responses.activate
def test_projects_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "organizations/acme/projects/?all_projects=1"
    responses.add(responses.GET, url, json=[])
    sentry_api.projects("acme")
    assert responses.calls[0].request.url == url


@responses.activate
def test_get_project_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "projects/acme/backend/"
    responses.add(responses.GET, url, json={})
    sentry_api.project("acme", "backend")
    assert responses.calls[0].request.url == url
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_sentry_api_endpoints.py -k "organizations_calls or projects_calls or get_project_calls" -v`
Expected: all 3 PASS — these pin what the code does today.

- [ ] **Step 3: Check the docs**

Fetch https://docs.sentry.io/api/organizations/ and https://docs.sentry.io/api/projects/ and compare each pinned URL shape against the current documented path and required query params.

- [ ] **Step 4: Record the findings**

Append 3 rows to `docs/sentry-api-audit.md` (Verdict: `Current` or `Deprecated → <replacement>`; Env var column blank unless Step 5b applies).

- [ ] **Step 5a: If all three are current — no code change**

Leave `libs/sentry.py` untouched.

- [ ] **Step 5b: If the docs name a replacement for any of the three — add the env-gated branch**

In the affected method, branch on `self.use_legacy_api` per the plan's "Backward-compatible migration mechanism": the `if` branch keeps today's exact URL, the `else` branch calls the documented replacement. Add a second, parametrized pin test asserting the new URL when `use_legacy_api=False`:

```python
@responses.activate
def test_organizations_calls_new_endpoint_when_opted_in():
    api = SentryAPI(base_url=BASE_URL, auth_token="test-token", use_legacy_api=False)
    url = BASE_URL + "<replacement-path>"  # from the docs check in Step 3
    responses.add(responses.GET, url, json=[])
    api.organizations()
    assert responses.calls[0].request.url == url
```

Note the env var in the `docs/sentry-api-audit.md` row's Action/Env var columns, and add a line for `SENTRY_USE_LEGACY_API` to `README.md`'s env var table if this is the first method to use it.

Run: `pytest tests/test_sentry_api_endpoints.py -k "organizations_calls or projects_calls or get_project_calls" -v`
Expected: all PASS (both legacy-default and opted-in cases for any migrated method).

- [ ] **Step 6: Commit**

```bash
git add tests/test_sentry_api_endpoints.py docs/sentry-api-audit.md libs/sentry.py README.md
git commit -m "audit: verify organizations/projects endpoints against current Sentry docs (#114)"
```

---

### Task 3: Verify project stats endpoint

**Files:**
- Modify: `tests/test_sentry_api_endpoints.py`
- Modify: `docs/sentry-api-audit.md`
- Modify (only if docs require it): `libs/sentry.py`, `README.md`

**Interfaces:**
- Consumes: `sentry_api` fixture from Task 1.
- Covers: `SentryAPI.project_stats(org_slug, proj_slug, stat, ...)` → `GET projects/{org}/{proj_slug}/stats/?stat=...`. This is the method PR #53 already fixed the month-start timestamp bug in — audit its endpoint shape, not its date math (already resolved).

- [ ] **Step 1: Write the pin test**

```python
@responses.activate
def test_project_stats_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "projects/acme/backend/stats/?stat=received"
    responses.add(responses.GET, url, json=[])
    sentry_api.project_stats("acme", "backend", "received")
    assert responses.calls[0].request.url == url
```

- [ ] **Step 2: Run it**

Run: `pytest tests/test_sentry_api_endpoints.py -k project_stats -v`
Expected: PASS.

- [ ] **Step 3: Check the docs**

Fetch https://docs.sentry.io/api/projects/retrieve-event-counts-for-a-project/ and compare against the pinned URL and `stat` values the code sends (`received`, `rejected`, `blacklisted` — check `helpers/prometheus.py` callers for the actual set in use).

- [ ] **Step 4: Record the finding**

Append a row to `docs/sentry-api-audit.md`.

- [ ] **Step 5: Migrate if needed**

Same env-gated pattern as Task 2 Step 5b — add the `use_legacy_api` branch if the docs name a replacement, add the parametrized pin test for the opted-in case, update `README.md` if `SENTRY_USE_LEGACY_API` isn't documented yet, re-run Step 2's command until all cases pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_sentry_api_endpoints.py docs/sentry-api-audit.md libs/sentry.py README.md
git commit -m "audit: verify project stats endpoint against current Sentry docs (#114)"
```

---

### Task 4: Verify issue events & current-release endpoints, fix known URL bug

**Files:**
- Modify: `libs/sentry.py` (`issue_events` method)
- Modify: `tests/test_sentry_api_endpoints.py`
- Modify: `docs/sentry-api-audit.md`
- Modify (only if docs require it): `README.md`

**Interfaces:**
- Consumes: `sentry_api` fixture from Task 1.
- Covers: `SentryAPI.issue_events(issue_id, environment=None)` → `GET issues/{issue_id}/events/`, `SentryAPI.current_release(issue_id)` → `GET issues/{issue_id}/current-release/`.

This task fixes a real, already-confirmed bug independent of the docs verification: when `environment` is passed, `issue_events` appends `"&environment=" + environment` directly onto a URL that has no `?` yet, producing a malformed request like `issues/123/events/&environment=prod`. Fix this regardless of what the docs-verification step finds. This is a pure correctness fix, not a deprecation, so it ships unconditionally — no env gate.

- [ ] **Step 1: Write a failing test for the URL bug**

```python
@responses.activate
def test_issue_events_with_environment_builds_valid_query_string(sentry_api):
    url = BASE_URL + "issues/123/events/?environment=production"
    responses.add(responses.GET, url, json=[])
    sentry_api.issue_events("123", environment="production")
    assert responses.calls[0].request.url == url


@responses.activate
def test_issue_events_without_environment_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "issues/123/events/"
    responses.add(responses.GET, url, json=[])
    sentry_api.issue_events("123")
    assert responses.calls[0].request.url == url


@responses.activate
def test_current_release_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "issues/123/current-release/"
    responses.add(responses.GET, url, json={})
    sentry_api.current_release("123")
    assert responses.calls[0].request.url == url
```

- [ ] **Step 2: Run the tests to see the bug reproduce**

Run: `pytest tests/test_sentry_api_endpoints.py -k "issue_events or current_release" -v`
Expected: `test_issue_events_with_environment_builds_valid_query_string` FAILS (actual URL contains `&environment=` with no preceding `?`); the other two PASS.

- [ ] **Step 3: Fix the query-string construction in `libs/sentry.py`**

In `issue_events`, build the base path `issues/{}/events/`.format(issue_id) once, then append `?environment={}`.format(environment) when `environment` is truthy, instead of unconditionally prefixing with `&`.

- [ ] **Step 4: Run the tests again**

Run: `pytest tests/test_sentry_api_endpoints.py -k "issue_events or current_release" -v`
Expected: all 3 PASS.

- [ ] **Step 5: Check the docs**

Fetch the current "list an issue's events" and "retrieve the current release for an issue" pages under https://docs.sentry.io/api/events/ and compare against the pinned URLs.

- [ ] **Step 6: Record the findings and migrate if needed**

Append rows to `docs/sentry-api-audit.md`, noting the query-string bug fix in the Action column for `issue_events` regardless of the deprecation verdict. If either endpoint is confirmed deprecated, apply the same env-gated pattern as Task 2 Step 5b (add the branch, add the opted-in pin test, update `README.md` if needed) and re-run Step 4's command.

- [ ] **Step 7: Commit**

```bash
git add libs/sentry.py tests/test_sentry_api_endpoints.py docs/sentry-api-audit.md README.md
git commit -m "fix: correct malformed query string in issue_events; audit issue endpoints (#114)"
```

---

### Task 5: Verify environments & issues (project-scoped) endpoints

**Files:**
- Modify: `tests/test_sentry_api_endpoints.py`
- Modify: `docs/sentry-api-audit.md`
- Modify (only if docs require it): `libs/sentry.py`, `README.md`

**Interfaces:**
- Consumes: `sentry_api` fixture from Task 1.
- Covers: `SentryAPI.environments(org_slug, proj_slug)` → `GET projects/{org}/{proj_slug}/environments/`, `SentryAPI.issues(org_slug, proj_slug, ...)` → `GET projects/{org}/{proj_slug}/issues/?...`. `issues()` is the method PR #20 already fixed (env-less projects, timestamp parsing) — audit the endpoint shape, not that already-resolved logic.

- [ ] **Step 1: Write the pin tests**

```python
@responses.activate
def test_environments_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "projects/acme/backend/environments/"
    responses.add(responses.GET, url, json=[])
    sentry_api.environments("acme", "backend")
    assert responses.calls[0].request.url == url


@responses.activate
def test_issues_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "projects/acme/backend/issues/?statsPeriod=24h&query=is%3Aunresolved"
    responses.add(responses.GET, url, json=[])
    sentry_api.issues("acme", "backend", query="is:unresolved", stats_period="24h")
    assert responses.calls[0].request.url == url
```

(Adjust the `issues()` call's keyword arguments in Step 1 to match its real signature in `libs/sentry.py` once merged with #20 — read the method signature before writing this test, since #20 changes how environments are handled.)

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_sentry_api_endpoints.py -k "environments_calls or issues_calls" -v`
Expected: both PASS.

- [ ] **Step 3: Check the docs**

Fetch https://docs.sentry.io/api/events/list-a-projects-issues/ and the environments listing page, compare against the pinned URLs and query params.

- [ ] **Step 4: Record the findings**

Append rows to `docs/sentry-api-audit.md`.

- [ ] **Step 5: Migrate if needed**

Same env-gated pattern as Task 2 Step 5b. Note from earlier PR review: Sentry's project-scoped `issues` listing has, in some contexts, been steered toward an organization-scoped equivalent — confirm the *current* status from the fetched docs rather than assuming, since this needs to be re-checked live against docs.sentry.io/api/ rather than carried over from memory.

- [ ] **Step 6: Commit**

```bash
git add tests/test_sentry_api_endpoints.py docs/sentry-api-audit.md libs/sentry.py README.md
git commit -m "audit: verify environments/issues endpoints against current Sentry docs (#114)"
```

---

### Task 6: Verify releases & keys endpoints

**Files:**
- Modify: `tests/test_sentry_api_endpoints.py`
- Modify: `docs/sentry-api-audit.md`
- Modify (only if docs require it): `libs/sentry.py`, `README.md`

**Interfaces:**
- Consumes: `sentry_api` fixture from Task 1.
- Covers: `SentryAPI.project_releases(org_slug, proj_slug)` → `GET organizations/{org}/releases/?project=...`, `SentryAPI.keys(org_slug, proj_slug)` → `GET projects/{org}/{proj_slug}/keys/` (used by `helpers/prometheus.py`'s rate-limit collection).

- [ ] **Step 1: Write the pin tests**

```python
@responses.activate
def test_project_releases_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "organizations/acme/releases/?project=backend"
    responses.add(responses.GET, url, json=[])
    sentry_api.project_releases("acme", "backend")
    assert responses.calls[0].request.url == url


@responses.activate
def test_keys_calls_expected_endpoint(sentry_api):
    url = BASE_URL + "projects/acme/backend/keys/"
    responses.add(responses.GET, url, json=[])
    sentry_api.keys("acme", "backend")
    assert responses.calls[0].request.url == url
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_sentry_api_endpoints.py -k "project_releases_calls or keys_calls" -v`
Expected: both PASS.

- [ ] **Step 3: Check the docs**

Fetch https://docs.sentry.io/api/releases/ and https://docs.sentry.io/api/projects/list-a-projects-client-keys/, compare against the pinned URLs.

- [ ] **Step 4: Record the findings**

Append rows to `docs/sentry-api-audit.md`.

- [ ] **Step 5: Migrate if needed**

Same env-gated pattern as Task 2 Step 5b.

- [ ] **Step 6: Commit**

```bash
git add tests/test_sentry_api_endpoints.py docs/sentry-api-audit.md libs/sentry.py README.md
git commit -m "audit: verify releases/keys endpoints against current Sentry docs (#114)"
```

---

### Task 7: Finalize — full verification, summary, stop locally

**Files:**
- Modify: `docs/sentry-api-audit.md` (add a one-paragraph summary at the top, above the table)
- Modify: `README.md` (confirm `SENTRY_USE_LEGACY_API` entry is complete if it was used)

**Interfaces:**
- Consumes: the completed table from Tasks 2–6, and the Docker test runner from Task 1.

- [ ] **Step 1: Run the full test suite one last time, both ways**

Run: `pytest -v`
Expected: every test in `tests/test_sentry_api_endpoints.py` PASSES.

Run: `docker compose run --rm tests`
Expected: same suite, same result, in a clean container.

- [ ] **Step 2: Verify the production image is unaffected**

Run: `docker build .` (no `--target`)
Expected: succeeds, produces the `base` stage — same `CMD` as before this plan, no dev dependencies baked in.

- [ ] **Step 3: Add a summary paragraph to the top of `docs/sentry-api-audit.md`**

Write 2-4 sentences stating how many endpoints were audited, how many were current vs. gained a `use_legacy_api` branch, and cross-reference the `eventsv2`→`events` finding already tracked on PR #58 (don't duplicate that row here — it's not on `master` yet).

- [ ] **Step 4: Confirm `README.md`'s env var table is complete**

If any task added a `use_legacy_api` branch, confirm `SENTRY_USE_LEGACY_API` is documented once, clearly, with its default (`"True"`) and what setting it to `"False"` does.

- [ ] **Step 5: Commit**

```bash
git add docs/sentry-api-audit.md README.md
git commit -m "docs: finalize Sentry API audit summary (#114)"
```

- [ ] **Step 6: Stop — do not push or publish**

This plan's deliverable stays local in this worktree once Step 5 is committed. Do **not** run `git push`, `gh issue comment`, or `gh issue close` — those require the user's explicit go-ahead in a separate request, per the plan's Global Constraints.

---

## Self-Review Notes

- **Spec coverage:** every `SentryAPI` method with a live HTTP call is covered across Tasks 2–6 (`organizations`, `projects`, `project`, `project_stats`, `issue_events`, `current_release`, `environments`, `issues`, `project_releases`, `keys`). The already-confirmed `eventsv2` finding from PR #58 is cross-referenced in Task 7 rather than re-audited, per the Global Constraints. Docker test harness and retrocompatible env-var mechanism are covered in Task 1 (setup) and Task 2's Step 5b pattern (reused by Tasks 3, 5, 6).
- **Known bug folded in:** the `issue_events` malformed query-string bug is fixed in Task 4 regardless of the deprecation verdict, unconditionally (not env-gated), since it's a correctness fix independent of Sentry's API version.
- **No breaking changes:** the multi-stage `Dockerfile`'s `base` stage is byte-for-byte what exists today; `docker-compose.yaml`'s three existing services are untouched; `SENTRY_USE_LEGACY_API` defaults to `"True"`, making every migrated method a no-op until a deployment opts in.
- **Placeholder scan:** every step either has real code/commands or a fully-specified conditional — no "add appropriate handling"-style steps.
- **Type/signature consistency:** all pin tests call `sentry_api` (the Task 1 fixture) and reference method names as they exist in `libs/sentry.py` today; Task 5's test carries an explicit note to re-check `issues()`'s exact signature after #20 merges.
- **Publish constraint:** Task 7 Step 6 explicitly stops short of pushing or commenting on #114 — this corrects the earlier draft's auto-push step, which conflicted with the user's standing "review locally before anything" instruction.
