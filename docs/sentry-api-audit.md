# Sentry API Audit

This document tracks findings from auditing the Sentry API endpoints used by the sentry-prometheus-exporter, as described in issue #114. See https://docs.sentry.io/api/ for the full API documentation.

| SentryAPI method | Endpoint (as called today) | Docs page checked | Verdict | Action | Env var |
|---|---|---|---|---|---|
| `organizations()` | `GET organizations/` | https://docs.sentry.io/api/users/list-your-organizations/ (linked from index https://docs.sentry.io/api/organizations/) | Current — docs show `GET /api/0/organizations/` with no deprecation notice; the endpoint moved documentation location (now filed under "Users") but the path is unchanged. | None | |
| `projects(org_slug)` | `GET organizations/{org}/projects/?all_projects=1` | https://docs.sentry.io/api/organizations/list-an-organizations-projects/ | Current — documented path is `GET /api/0/organizations/{organization_id_or_slug}/projects/`, matching what's called today. The `all_projects=1` query param is not documented (only `cursor`, `per_page`, `query` are listed) but is not flagged deprecated or rejected; treat as an undocumented/legacy passthrough param, not a broken endpoint. | None (query param not in current docs; monitor) | |
| `get_project(org_slug, project_slug)` | `GET projects/{org}/{proj_slug}/` | https://docs.sentry.io/api/projects/retrieve-a-project/ | Current — documented path is `GET /api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/`, matching what's called today (slugs are accepted values for both path segments). No deprecation notice. | None | |
