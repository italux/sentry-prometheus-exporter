# Sentry API Audit

This document tracks findings from auditing the Sentry API endpoints used by the sentry-prometheus-exporter, as described in issue #114. See https://docs.sentry.io/api/ for the full API documentation.

## Summary

10 SentryAPI methods were audited against live docs.sentry.io/api/ pages. 9 methods were confirmed current with no code changes required. 1 method (`issues()`) was found deprecated and has been migrated behind the new `SENTRY_USE_LEGACY_API` environment variable (default `"True"` preserves today's behavior; set to `"False"` to use the recommended organization-scoped endpoint). Additionally, a genuine bug in `issue_events`'s query-string construction was discovered and fixed: when the `environment` parameter was passed, the code was appending `&environment=...` without a leading `?`, creating a malformed URL. This has been corrected to properly format the query string. Note: The separately-tracked deprecation of `eventsv2` → `events` flagged in PR #58 is not re-audited here since that PR is not yet merged to master.

| SentryAPI method | Endpoint (as called today) | Docs page checked | Verdict | Action | Env var |
|---|---|---|---|---|---|
| `organizations()` | `/api/0/organizations/` | https://docs.sentry.io/api/organizations/ | Current | None | — |
| `projects(org_slug)` | `/api/0/organizations/{organization_id_or_slug}/projects/?all_projects=1` | https://docs.sentry.io/api/organizations/list-an-organizations-projects/ | Current | None | — |
| `get_project(org_slug, proj_slug)` | `/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/` | https://docs.sentry.io/api/projects/retrieve-a-project/ | Current | None | — |
| `project_stats(org_slug, proj_slug, stat=...)` | `/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/stats/?stat={stat}&since={since}&until={until}` | https://docs.sentry.io/api/projects/retrieve-project-stats/ | Current | None | — |
| `issue_events(issue_id, environment=None, ...)` | `/api/0/issues/{issue_id}/events/` (with optional `?environment={env}&sort=date`) | https://docs.sentry.io/api/events/list-an-issues-events/ | Current | Bug fix: query string construction | — |
| `issue_release(issue_id, environment=None)` | `/api/0/issues/{issue_id}/current-release/` (with optional `?environment={env}`) | https://docs.sentry.io/api/events/retrieve-the-current-release-for-an-issue/ | Current | None | — |
| `environments(org_slug, proj_slug)` | `/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/environments/` | https://docs.sentry.io/api/projects/list-an-environments/ | Current | None | — |
| `issues(org_slug, proj_slug, query=..., stats_period=...)` | `/api/0/organizations/{organization_id_or_slug}/issues/?project={proj_id}&sort=date&query=age%3A-{age}` (+ optional `&environment={env}`) | https://docs.sentry.io/api/events/list-an-organizations-issues/ | Deprecated | Migrated behind env var | `SENTRY_USE_LEGACY_API` |
| `project_releases(org_slug, proj_slug, query=None, environment=None)` | `/api/0/organizations/{organization_id_or_slug}/releases/?project={project_id}&sort=date` (with optional `&environment={env}`) | https://docs.sentry.io/api/releases/list-an-organizations-releases/ | Current | None | — |
| `rate_limit(org_slug, project_slug)` | `/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/keys/` | https://docs.sentry.io/api/projects/list-a-projects-client-keys/ | Current | None | — |
