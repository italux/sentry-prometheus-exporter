# CLAUDE.md

Guidance for Claude Code (and other agents) working in this repository.

## What this is

A small Flask app that polls the Sentry Web API and re-exposes org/project metrics (open issues, event counts, key rate limits) in Prometheus exposition format. It's a single-purpose exporter, not a service with a database — all state is either fetched live from Sentry or held in a 2-minute JSON file cache at `/tmp/sentry-prometheus-exporter-cache.json`.

## Architecture

```
exporter.py            Flask app: routes, env-var config, Basic Auth, healthz
libs/sentry.py         SentryAPI — thin wrapper around Sentry's REST API
helpers/prometheus.py  SentryCollector — builds Prometheus metric families
helpers/utils.py       JSON file cache (write_cache/get_cached) + healthz probes
```

Request flow: `GET /metrics/` in `exporter.py` builds a fresh `SentryAPI`, clears the Prometheus `REGISTRY` (`clean_registry()`), registers a new `SentryCollector`, and delegates to `prometheus_client`'s WSGI app via `DispatcherMiddleware`. All the actual work happens lazily inside `SentryCollector.collect()`, which is called by `prometheus_client` when it renders the response — not by `exporter.py` directly.

`SentryCollector` does not call `SentryAPI` on every scrape: it first checks `helpers.utils.get_cached()` for a live cache file and only calls the API (`__build_sentry_data_from_api`) on a cache miss/expiry. When it does hit the API, it also writes the result back to the cache file. Keep this in mind when debugging "stale metric" reports — the fix may be a cache TTL issue, not an API issue.

`SentryCollector.__init__` takes `metric_scraping_config` as a **positional list** of 6 string booleans (`"True"`/`"False"`, not real Python bools): `[issue_metrics, events_metrics, rate_limit_metrics, get_1h, get_24h, get_14d]`, built by `exporter.get_metric_config()`. If you add a new scrape toggle, you must update the list in both places, in order — there's no named-arg safety net here.

### Metrics emitted

- `sentry_issues` — `GaugeHistogramMetricFamily`, issues bucketed by age (1h/24h/14d)
- `sentry_open_issue_events` — `GaugeMetricFamily`, per-issue detail (only 1h-window issues, see below)
- `sentry_events` — `CounterMetricFamily`, total events per project (received/rejected/blacklisted)
- `sentry_rate_limit_events_sec` — `GaugeMetricFamily`, configured key rate limit

**Known quirk:** `sentry_open_issue_events` is only ever populated from the `1h` issue bucket (`helpers/prometheus.py`, in `collect()`), regardless of which age buckets are enabled. This looks intentional (avoids emitting a huge number of per-issue label combinations) but is easy to mistake for a bug — don't "fix" it without checking with the maintainer first.

## Configuration

Everything is env-var driven (see `exporter.py` top and `README.md`). Notable ones:

- `SENTRY_BASE_URL` (default `https://sentry.io/api/0/`), `SENTRY_AUTH_TOKEN`, `SENTRY_EXPORTER_ORG` (required)
- `SENTRY_EXPORTER_PROJECTS` — comma-separated slugs; omit to auto-discover all projects
- `SENTRY_SCRAPE_ISSUE_METRICS` / `SENTRY_SCRAPE_EVENT_METRICS` / `SENTRY_SCRAPE_RATE_LIMIT_METRICS`
- `SENTRY_ISSUES_1H` / `SENTRY_ISSUES_24H` / `SENTRY_ISSUES_14D`
- `SENTRY_EXPORTER_BASIC_AUTH(_USER|_PASS)`
- `SENTRY_RETRY_TRIES` / `_DELAY` / `_MAX_DELAY` / `_BACKOFF` / `_JITTER` (used by `libs/sentry.py`'s `@retry`)

All of these are compared against the **string** `"True"`, not parsed as booleans — `SENTRY_SCRAPE_ISSUE_METRICS=false` (lowercase) will NOT disable the feature. Preserve this comparison style if you touch config parsing, or fix it repo-wide in one pass rather than mixing conventions.

## Running locally

```sh
export SENTRY_BASE_URL="https://sentry.io/api/0/"
export SENTRY_AUTH_TOKEN="[token]"
export SENTRY_EXPORTER_ORG="[org-slug]"
python exporter.py            # dev server, or:
gunicorn -w 4 -b 0.0.0.0:9790 exporter:app   # prod-like, matches Dockerfile CMD
```

```sh
docker-compose up -d          # brings up prometheus + grafana + this exporter
```

`docker-compose.yaml` expects a local `.env` file (not committed) with the vars above.

## Testing

**There is currently no `tests/` directory or test tooling on `master`.** CI (`.github/workflows/lint.yml`) only lints Python, and only runs lint — not tests:

- `black -l 99 -t py37 --check .` (Black, line length 99, Python 3.7 target)

If you add tests, match the pattern already prototyped on the `sentry-api-audit-plan` worktree/branch: `pytest` via `requirements-dev.txt`, a `tests/` package, and a dedicated `test` build stage in the Dockerfile (`FROM python:3.8-slim AS test`, installs both requirement files, `CMD ["pytest"]`) — do not just bolt pytest onto the existing `python:3.7-slim` runtime image. Note **3.7 vs 3.8**: the runtime image is pinned to `python:3.7-slim` while newer dev/test dependencies may require 3.8+; if you touch the Dockerfile, keep the runtime and test stages on the Python versions that actually satisfy each requirements file — don't assume they match.

Before merging, actually run Black locally rather than relying on CI alone:

```sh
pip install black==<version pinned by lgeiger/black-action@v1.0.1>
black -l 99 -t py37 --check .
```

## Sentry API surface (`libs/sentry.py`)

`SentryAPI` methods each hand-pick which fields to keep from Sentry's JSON response (e.g. `get_org` returns only `id/slug/name/status/platform`) — if a new metric needs a field that isn't already being kept, you'll need to add it to the relevant method's dict, not just read it off the raw response.

All GET requests share one private `__get()` with `@retry` (from the `retry` package) on `requests.exceptions.HTTPError`, configured via the `SENTRY_RETRY_*` env vars. `__post` is a stub (`raise NotImplementedError`) — this class is read-only by design; don't add mutating calls without discussing the retry/idempotency implications first.

Sentry rate-limits to ~3 req/s. The exporter is **serial** (no concurrency) — for orgs with many projects/environments this can be slow enough to blow past Prometheus's scrape timeout. If you're asked to speed this up, prefer batching/async at the `SentryCollector` level over touching the retry logic.

## Code style

- Follow existing formatting: Black with `-l 99 -t py37` (100 columns is wrong here — it's 99). Run Black before committing; CI will fail otherwise.
- `.format()`-style string formatting is used throughout (not f-strings) — match it in new code for consistency, this repo still targets Python 3.7.
- Logging uses the stdlib `logging` module with module-level `log = logging.getLogger(__name__)`; log levels follow a `metadata: ...` / `collector: ...` / `cache: ...` / `auth: ...` prefix convention in message strings — keep using a prefix that matches the surrounding code when adding new log lines.
- Docstrings are Google-style (`Args:` / `Returns:` / `Raises:`) — match this in `libs/sentry.py` when adding methods there.

## Known limitations (don't "fix" silently — flag first)

- No horizontal scaling / concurrency story; a single slow scrape blocks the whole exporter (Flask dev server / gunicorn workers each block on their own request).
- The JSON file cache is a single shared path (`/tmp/sentry-prometheus-exporter-cache.json`) with no locking — fine for a single-process deployment, unsafe if you ever run multiple gunicorn workers scraping independently (each worker keeps re-caching).
- `readiness()` in `helpers/utils.py` only instantiates `SentryAPI`; it never actually calls Sentry, so `/healthz/ready` can report healthy even when the auth token or base URL is wrong.
