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

`GET /metrics/` in `exporter.py` builds a fresh `SentryAPI`, swaps the previously-registered `SentryCollector` out of the module-level `registry` (a `CollectorRegistry` instance, tracked via the `current_collector` global) for a new one, then delegates to `prometheus_client`'s WSGI app via `DispatcherMiddleware`. All actual work happens lazily inside `SentryCollector.collect()`, invoked by `prometheus_client` when it renders the response — not by `exporter.py` directly.

`SentryCollector` does not call `SentryAPI` on every scrape: it first checks `helpers.utils.get_cached()` for a live cache file and only calls the API (`__build_sentry_data_from_api`) on a cache miss/expiry. When it does hit the API, it also writes the result back to the cache file. Keep this in mind when debugging "stale metric" reports — the fix may be a cache TTL issue, not an API issue.

`SentryCollector.__init__` takes `metric_scraping_config` as a **positional list** of 6 string booleans (`"True"`/`"False"`, not real Python bools): `[issue_metrics, events_metrics, rate_limit_metrics, get_1h, get_24h, get_14d]`, built by `exporter.get_metric_config()`. If you add a new scrape toggle, you must update the list in both places, in order — there's no named-arg safety net here.

### Metrics emitted

Names and user-facing purpose are documented in README's "Metrics" section; what's worth knowing here is the underlying Prometheus type and a caveat that isn't in README:

- `sentry_issues` — `GaugeHistogramMetricFamily`, issues bucketed by age (1h/24h/14d)
- `sentry_open_issue_events` — `GaugeMetricFamily`, per-issue detail (only 1h-window issues, see below)
- `sentry_events` — `CounterMetricFamily`, total events per project (received/rejected/blacklisted)
- `sentry_rate_limit_events_sec` — `GaugeMetricFamily`, configured key rate limit

**Known quirk:** `sentry_open_issue_events` is only ever populated from the `1h` issue bucket (`helpers/prometheus.py`, in `collect()`), regardless of which age buckets are enabled. This looks intentional (avoids high per-issue label cardinality), not a bug — don't "fix" it without checking with the maintainer first.

## Configuration

Everything is env-var driven. See `README.md`'s "Project Configuration", "Metric Configuration", and "Basic Authentication" sections for the full variable reference (names, defaults, purpose) — don't duplicate that list here, keep it in sync in one place.

Gotcha not spelled out in README: every toggle var is compared against the **string** `"True"`, not parsed as a real boolean — `SENTRY_SCRAPE_ISSUE_METRICS=false` (lowercase) will **not** disable the feature, it has to be exactly `"True"` or anything else counts as false. Preserve this comparison style if you touch config parsing, or fix it repo-wide in one pass rather than mixing conventions.

## Running locally

See `README.md`'s "Getting Started" section for the env vars, `python exporter.py`, and `docker-compose up -d` flows. Locally this maps to gunicorn, not the Flask dev server, to match prod (matches the Dockerfile `CMD`):

```sh
gunicorn -w 4 -b 0.0.0.0:9790 exporter:app
```

## Testing

**There is currently no `tests/` directory or test tooling on `master`.** CI (`.github/workflows/lint.yml`) only runs Black lint — no tests:

```sh
black -l 99 -t py37 --check .
```

If you add tests:

- Don't bolt pytest onto the existing single-stage `python:3.7-slim` Dockerfile — give the test stage its own build stage and its own Python version (whatever `requirements-dev.txt` actually needs), independent of the runtime stage's 3.7 pin.
- Run the same check as CI locally before pushing rather than relying on CI alone — install whatever Black version is pinned by the `lgeiger/black-action` step in `.github/workflows/lint.yml`.

## Sentry API surface (`libs/sentry.py`)

`SentryAPI` methods each hand-pick which fields to keep from Sentry's JSON response (e.g. `get_org` returns only `id/slug/name/status/platform`) — if a new metric needs a field that isn't already being kept, you'll need to add it to the relevant method's dict, not just read it off the raw response.

All GET requests share one private `__get()` with `@retry` (from the `retry` package) on `requests.exceptions.HTTPError`, configured via the `SENTRY_RETRY_*` env vars. `__post` is a stub (`raise NotImplementedError`) — this class is read-only by design; don't add mutating calls without discussing the retry/idempotency implications first.

Sentry rate-limits to ~3 req/s (see README's Limitations section), and the exporter has no concurrency (see "Known limitations" below) — for orgs with many projects/environments this combination can be slow enough to blow past Prometheus's scrape timeout.

## Code style

- Follow existing formatting: Black, same invocation as CI (see Testing above) — 99 columns, not 100. Run it before committing; CI will fail otherwise.
- `.format()`-style string formatting is used throughout (not f-strings) — match it in new code for consistency, this repo still targets Python 3.7.
- Logging uses the stdlib `logging` module with module-level `log = logging.getLogger(__name__)`; log levels follow a `metadata: ...` / `collector: ...` / `cache: ...` / `auth: ...` prefix convention in message strings — keep using a prefix that matches the surrounding code when adding new log lines.
- Docstrings are Google-style (`Args:` / `Returns:` / `Raises:`) — match this in `libs/sentry.py` when adding methods there.

## Known limitations (don't "fix" silently — flag first)

- No horizontal scaling / concurrency story; a single slow scrape blocks the whole exporter (Flask dev server / gunicorn workers each block on their own request).
- The JSON file cache is a single shared path (`/tmp/sentry-prometheus-exporter-cache.json`) with no locking — fine for a single-process deployment, unsafe if you ever run multiple gunicorn workers scraping independently (each worker keeps re-caching).
- `readiness()` in `helpers/utils.py` only instantiates `SentryAPI`; it never actually calls Sentry, so `/healthz/ready` can report healthy even when the auth token or base URL is wrong.
