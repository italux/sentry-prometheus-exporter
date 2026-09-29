import logging
import threading
import time
from datetime import datetime, timedelta
from os import getenv
from uuid import uuid4

from prometheus_client.core import (
    CounterMetricFamily,
    GaugeHistogramMetricFamily,
    GaugeMetricFamily,
)

from helpers.utils import get_cached, write_cache

# constants for caching file
JSON_CACHE_FILE = "/tmp/sentry-prometheus-exporter-cache.json"
DEFAULT_CACHE_EXPIRE_TIMESTAMP = int(datetime.timestamp(datetime.now() + timedelta(minutes=2)))

# Background refresh interval for stats_v2 (seconds). A daemon thread refreshes the
# in-memory cache on this cadence; collect() only reads the cache, so a slow or
# unreachable Sentry API never blocks a Prometheus scrape.
STATS_V2_REFRESH_INTERVAL_SECONDS = int(getenv("SENTRY_REFRESH_INTERVAL_SECONDS", "60"))

# Cache age above which we log a staleness WARNING (refresher likely failing).
# Data is still served — staleness is exposed via the last-success timestamp metric.
STATS_V2_CACHE_MAX_AGE_SECONDS = 900

log = logging.getLogger(__name__)


class SentryCollector(object):
    """A simple :class:`SentryCollector <SentryCollector>` returns a list of Metric objects.

    Proxy metrics from sentry building consistent with the Prometheus exposition formats:

    GaugeHistogramMetricFamily: projects issues split into 3 issues age buckets: 1h, 24h, and 14d
    GaugeMetricFamily:          count the open issues adding several labels to help aggregation
    CounterMetricFamily:        total projects events count

    Typical usage example:

      >>> from helpers.prometheus import SentryCollector
      >>> REGISTRY.register(SentryCollector(sentry, org_slug, projects_slug))
    """

    def __init__(
        self,
        sentry_api,
        sentry_org_slug,
        metric_scraping_config,
        sentry_projects_slug=None,
    ):
        """Inits SentryCollector with a SentryAPI object"""
        super(SentryCollector, self).__init__()
        self.__sentry_api = sentry_api
        self.sentry_org_slug = sentry_org_slug
        self.sentry_projects_slug = sentry_projects_slug
        self.issue_metrics = metric_scraping_config[0]
        self.events_metrics = metric_scraping_config[1]
        self.rate_limit_metrics = metric_scraping_config[2]
        self.get_1h_metrics = metric_scraping_config[3]
        self.get_24h_metrics = metric_scraping_config[4]
        self.get_14d_metrics = metric_scraping_config[5]

    def __build_sentry_data_from_api(self):
        """Build a local data structure from sentry API calls.

        Returns:
            A dict mapping keys to the corresponding sentry authenticated session.

            The metadata key will store organization and projects metadata info
            (i.e.: slug names, ids, status, etc...) and projects_data key will store
            project's issues data, each key is a corrensponding environment
            which contains 3 different ages: 1h, 24h and 14d lists of issues

            Example:
                data = {
                    "metadata": {
                        "orgs": org,
                        "projects": projects,
                        "orgs_slug": orgs_slug,
                        "projects_slug": projects_slug,
                        "projects_envs": projects_envs,
                    },
                    "projects_data" : {
                        "project_slug": {
                            "production": {
                                "1h": [],
                                "24h": [],
                                "14d": []
                            },
                            "staging": {
                                "1h": [],
                                "24h": [],
                                "14d": []
                            }
                        }
                    }
                }
        """

        projects_slug = []
        projects_envs = {}
        projects = []
        self.org = self.__sentry_api.get_org(self.sentry_org_slug)
        log.info("metadata: sentry organization: {org}".format(org=self.org.get("slug")))

        if self.sentry_projects_slug:
            log.info(
                "metadata: projects specified: {num_proj}".format(
                    num_proj=len(self.sentry_projects_slug.split(","))
                )
            )
            for project_slug in self.sentry_projects_slug.split(","):
                log.debug(
                    "metadata: getting {proj} project data from API".format(proj=project_slug)
                )
                project = self.__sentry_api.get_project(self.org.get("slug"), project_slug)
                projects.append(project)
                projects_slug.append(project_slug)
                envs = self.__sentry_api.environments(self.org.get("slug"), project)
                projects_envs[project.get("slug")] = envs
            log.info(
                "metadata: projects loaded from API: {num_proj}".format(num_proj=len(projects))
            )
        else:
            log.info(
                "metadata: no projects specified, loading from API".format(num_proj=len(projects))
            )
            for project in self.__sentry_api.projects(self.sentry_org_slug):
                projects.append(project)
                projects_slug.append(project.get("slug"))
                envs = self.__sentry_api.environments(self.org.get("slug"), project)
                projects_envs[project.get("slug")] = envs
            log.info(
                "metadata: projects loaded from API: {num_proj}".format(num_proj=len(projects))
            )

        log.debug("metadata: building projects metadata structure")
        data = {
            "metadata": {
                "org": self.org,
                "projects": projects,
                "projects_slug": projects_slug,
                "projects_envs": projects_envs,
            }
        }
        if self.issue_metrics == "True":
            __metadata = data.get("metadata")

            projects_issue_data = {}

            for project in __metadata.get("projects"):
                projects_issue_data[project.get("slug")] = {}
                envs = __metadata.get("projects_envs").get(project.get("slug"))
                envs = envs if envs else [None]
                for env in envs:
                    project_issues_1h = project_issues_24h = project_issues_14d = {}
                    if self.get_1h_metrics == "True":
                        log.debug(
                            "metadata: getting issues from api - project: {proj} env: {env} age: 1h".format(
                                proj=project.get("slug"), env=env
                            )
                        )
                        project_issues_1h = self.__sentry_api.issues(
                            self.org.get("slug"), project, env, age="1h"
                        )
                    if self.get_24h_metrics == "True":
                        log.debug(
                            "metadata: getting issues from api - project: {proj} env: {env} age: 24h".format(
                                proj=project.get("slug"), env=env
                            )
                        )
                        project_issues_24h = self.__sentry_api.issues(
                            self.org.get("slug"), project, env, age="24h"
                        )
                    if self.get_14d_metrics == "True":
                        log.debug(
                            "metadata: getting issues from api - project: {proj} env: {env} age: 14d".format(
                                proj=project.get("slug"), env=env
                            )
                        )
                        project_issues_14d = self.__sentry_api.issues(
                            self.org.get("slug"), project, env, age="14d"
                        )

                    log.debug("data structure: building projects issues data")
                    for k, v in project_issues_1h.items():
                        projects_issue_data[project.get("slug")][k] = {"1h": v}

                    for k, v in project_issues_24h.items():
                        projects_issue_data[project.get("slug")][k].update({"24h": v})

                    for k, v in project_issues_14d.items():
                        projects_issue_data[project.get("slug")][k].update({"14d": v})

            data["projects_data"] = projects_issue_data

        write_cache(JSON_CACHE_FILE, data, DEFAULT_CACHE_EXPIRE_TIMESTAMP)
        log.debug("cache: writing data structure to file: {cache}".format(cache=JSON_CACHE_FILE))
        return data

    def __build_sentry_data(self):
        data = get_cached(JSON_CACHE_FILE)

        if data is False:
            log.debug("cache: {cache} not found.".format(cache=JSON_CACHE_FILE))
            log.debug("cache: rebuilding from API...")
            api_data = self.__build_sentry_data_from_api()
            return api_data

        log.debug("cache: reading data structure from file: {cache}".format(cache=JSON_CACHE_FILE))
        return data

    def collect(self):
        """Yields metrics from the collectors in the registry."""

        __data = self.__build_sentry_data()
        __metadata = __data.get("metadata")
        __projects_data = __data.get("projects_data")

        self.org = __metadata.get("org")
        self.projects_data = {}

        if self.issue_metrics == "True":
            issues_histogram_metrics = GaugeHistogramMetricFamily(
                "sentry_issues",
                "Number of open issues (aka is:unresolved) per project",
                buckets=None,
                gsum_value=None,
                labels=[
                    "project_slug",
                    "environment",
                ],
                unit="",
            )

            log.info("collector: loading projects issues")
            for project in __metadata.get("projects"):
                envs = __metadata.get("projects_envs").get(project.get("slug"))
                project_issues = __projects_data.get(project.get("slug"))
                for env in envs:
                    log.debug(
                        "collector: loading issues - project: {proj} env: {env}".format(
                            proj=project.get("slug"), env=env
                        )
                    )

                    project_issues_1h = project_issues.get(env).get("1h")
                    project_issues_24h = project_issues.get(env).get("24h")
                    project_issues_14d = project_issues.get(env).get("14d")

                    events_1h = 0
                    events_24h = 0
                    events_14d = 0

                    if project_issues_1h:
                        for issue in project_issues_1h:
                            events_1h += int(issue.get("count") or 0)

                    if project_issues_24h:
                        for issue in project_issues_24h:
                            events_24h += int(issue.get("count") or 0)

                    if project_issues_14d:
                        for issue in project_issues_14d:
                            events_14d += int(issue.get("count") or 0)

                    sum_events = events_1h + events_24h + events_14d
                    histo_buckets = []
                    if self.get_1h_metrics == "True":
                        histo_buckets.append(("1h", float(events_1h)))
                    if self.get_24h_metrics == "True":
                        histo_buckets.append(("24h", float(events_24h)))
                    if self.get_14d_metrics == "True":
                        histo_buckets.append(("+Inf", float(events_14d)))
                    issues_histogram_metrics.add_metric(
                        labels=[
                            str(project.get("slug")),
                            str(env),
                        ],
                        buckets=histo_buckets,
                        gsum_value=int(sum_events),
                    )

            yield issues_histogram_metrics

            issues_metrics = GaugeMetricFamily(
                "sentry_open_issue_events",
                "Number of open issues (aka is:unresolved) per project",
                labels=[
                    "issue_id",
                    "logger",
                    "level",
                    "status",
                    "platform",
                    "project_slug",
                    "environment",
                    "release",
                    "isUnhandled",
                    "firstSeen",
                    "lastSeen",
                ],
            )

            for project in __metadata.get("projects"):
                envs = __metadata.get("projects_envs").get(project.get("slug"))
                project_issues = __projects_data.get(project.get("slug"))
                envs = envs if envs else [None]
                for env in envs:
                    project_issues_1h = (
                        project_issues.get(env).get("1h")
                        if env
                        else project_issues.get("all").get("1h")
                    )
                    for issue in project_issues_1h:
                        release = self.__sentry_api.issue_release(issue.get("id"), env)
                        first_seen = (
                            datetime.strptime(str(issue.get("firstSeen")), "%Y-%m-%dT%H:%M:%SZ")
                            if len(str(issue.get("firstSeen"))) == 20
                            else (
                                datetime.strptime(
                                    str(issue.get("firstSeen")), "%Y-%m-%dT%H:%M:%S.%fZ"
                                )
                                if issue.get("firstSeen")
                                else datetime.now()
                            )
                        )
                        last_seen = (
                            datetime.strptime(str(issue.get("lastSeen")), "%Y-%m-%dT%H:%M:%SZ")
                            if len(str(issue.get("lastSeen"))) == 20
                            else (
                                datetime.strptime(
                                    str(issue.get("lastSeen")), "%Y-%m-%dT%H:%M:%S.%fZ"
                                )
                                if issue.get("lastSeen")
                                else datetime.now()
                            )
                        )
                        issues_metrics.add_metric(
                            [
                                str(issue.get("id")),
                                str(issue.get("logger")) or "None",
                                str(issue.get("level")),
                                str(issue.get("status")),
                                str(issue.get("platform")),
                                str(issue.get("project").get("slug")),
                                str(env),
                                str(release),
                                str(issue.get("isUnhandled")),
                                str(
                                    datetime.strftime(
                                        first_seen,
                                        "%Y-%m-%d",
                                    )
                                ),
                                str(
                                    datetime.strftime(
                                        last_seen,
                                        "%Y-%m-%d",
                                    )
                                ),
                            ],
                            int(issue.get("count")),
                        )
            yield issues_metrics

        if self.events_metrics == "True":
            project_events_metrics = CounterMetricFamily(
                "sentry_events",
                "Total events counts per project",
                labels=[
                    "project_slug",
                    "stat",
                ],
            )

            for project in __metadata.get("projects"):
                events = self.__sentry_api.project_stats(self.org.get("slug"), project.get("slug"))
                for stat, value in events.items():
                    project_events_metrics.add_metric(
                        [
                            str(project.get("slug")),
                            str(stat),
                        ],
                        int(value),
                    )

            yield project_events_metrics

        if self.rate_limit_metrics == "True":
            project_rate_metrics = GaugeMetricFamily(
                "sentry_rate_limit_events_sec",
                "Rate limit events per second for a project",
                labels=["project_slug"],
            )

            for project in __metadata.get("projects"):
                rate_limit_second = self.__sentry_api.rate_limit(
                    self.org.get("slug"), project.get("slug")
                )
                project_rate_metrics.add_metric(
                    [str(project.get("slug"))], round(rate_limit_second, 6)
                )

            yield project_rate_metrics


class SentryStatsV2Collector(object):
    """Collector for organization-level stats using the efficient stats_v2 API.

    This collector uses a single API call to get stats for all projects,
    making it much faster and more efficient than the per-project approach.

    Typical usage example:

      >>> from helpers.prometheus import SentryStatsV2Collector
      >>> REGISTRY.register(SentryStatsV2Collector(sentry, org_slug, stats_period="1d"))
    """

    def __init__(
        self,
        sentry_api,
        sentry_org_slug,
        stats_period="1d",
        categories=None,
        billing_cycle_day=None,
        refresh_interval=None,
    ):
        """Inits SentryStatsV2Collector with a SentryAPI object"""
        super(SentryStatsV2Collector, self).__init__()
        self.__sentry_api = sentry_api
        self.sentry_org_slug = sentry_org_slug
        self.stats_period = stats_period
        self.categories = categories or ["error"]
        self.billing_cycle_day = billing_cycle_day
        self.refresh_interval = refresh_interval or STATS_V2_REFRESH_INTERVAL_SECONDS

    def _get_billing_period(self):
        """Calculate the start and end dates of the current Sentry billing period.

        Returns:
            Tuple of (start, end) as ISO 8601 strings, or (None, None) if billing_cycle_day is not set.
        """
        if not self.billing_cycle_day:
            return None, None

        now = datetime.utcnow()
        day = self.billing_cycle_day

        if now.day >= day:
            # Billing period started this month
            start = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
        else:
            # Billing period started last month
            first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month = first_of_month - timedelta(days=1)
            start = last_month.replace(day=day, hour=0, minute=0, second=0, microsecond=0)

        end = now

        return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")

    # In-memory cache shared across collector instances within a worker process
    # (class-level). A background daemon thread refreshes it on a fixed interval;
    # collect() only ever reads it, so a slow or unreachable Sentry API can never
    # block a Prometheus scrape. The cache survives collector re-registration but not
    # pod restarts, which is fine — the refresher repopulates it within one interval.
    _cache_lock = threading.Lock()
    _cached_data = None
    _cache_timestamp = None  # epoch seconds of last cache write
    _last_success_ts = None  # epoch seconds of last successful Sentry fetch
    _refresher_started = False
    _consecutive_failures = 0  # count of back-to-back failed refreshes
    _stale_logged = False  # ensures the "cache STALE" transition logs only once

    def _write_cache(self, data):
        """Store stats data in the in-memory cache (thread-safe)."""
        now = time.time()
        with SentryStatsV2Collector._cache_lock:
            SentryStatsV2Collector._cached_data = data
            SentryStatsV2Collector._cache_timestamp = now
            SentryStatsV2Collector._last_success_ts = now
        log.debug("cache: stats_v2 data cached in memory")

    def _read_cache(self):
        """Return the last-known-good cached data, or None if never populated.

        This is the sole data source for collect(): data is served regardless of
        age so metrics never gap during a Sentry outage. Prolonged staleness is
        observable via sentry_stats_v2_last_success_timestamp_seconds.
        """
        with SentryStatsV2Collector._cache_lock:
            data = SentryStatsV2Collector._cached_data
            ts = SentryStatsV2Collector._cache_timestamp
        if data is None:
            return None
        # Staleness is logged (once, on transition) by the refresher, not here —
        # collect() runs on every scrape and would otherwise spam the log.
        log.debug("cache: serving stats_v2 from memory cache (%.0fs old)", time.time() - (ts or 0))
        return data

    def _cache_age_seconds(self):
        """Age of the cached data in seconds, or None if the cache is empty."""
        with SentryStatsV2Collector._cache_lock:
            ts = SentryStatsV2Collector._cache_timestamp
        return None if ts is None else time.time() - ts

    def _last_success_desc(self):
        """Human-readable time since the last successful fetch (for log lines)."""
        with SentryStatsV2Collector._cache_lock:
            ts = SentryStatsV2Collector._last_success_ts
        return "never" if ts is None else "%.0fs ago" % (time.time() - ts)

    def _fetch_stats(self, billing_start, billing_end):
        """Fetch stats for all categories from Sentry and cache them on success.

        Raises on API failure — the caller (_refresh_once) owns failure logging
        and cache-staleness accounting. On success the cache is updated (leaving
        the last good data intact if a later category fails mid-cycle).
        """
        all_stats_data = {}
        for category in self.categories:
            log.debug("collector: fetching stats for category: %s", category)
            stats_data = self.__sentry_api.org_stats_v2(
                self.sentry_org_slug,
                stats_period=self.stats_period,
                categories=[category],
                start=billing_start,
                end=billing_end,
            )
            for project_slug, outcomes in stats_data.items():
                if project_slug not in all_stats_data:
                    all_stats_data[project_slug] = {}
                all_stats_data[project_slug][category] = outcomes
        self._write_cache(all_stats_data)
        return all_stats_data

    def _refresh_once(self):
        """Run one refresh cycle and log its impact on cache freshness clearly."""
        cls = SentryStatsV2Collector
        billing_start, billing_end = self._get_billing_period()
        if billing_start:
            log.debug(
                "collector: refreshing stats_v2 for billing period %s to %s",
                billing_start,
                billing_end,
            )

        try:
            data = self._fetch_stats(billing_start, billing_end)
        except Exception as e:
            cls._consecutive_failures += 1
            age = self._cache_age_seconds()
            cache_desc = "no cached data yet" if age is None else "cache now %.0fs old" % age
            log.error(
                "collector: Sentry stats_v2 fetch FAILED (%s) — %d consecutive failure(s), "
                "%s, last success %s",
                e,
                cls._consecutive_failures,
                cache_desc,
                self._last_success_desc(),
            )
            # Log the stale transition exactly once so it stands out without spamming.
            if age is not None and age > STATS_V2_CACHE_MAX_AGE_SECONDS and not cls._stale_logged:
                log.error(
                    "collector: stats_v2 cache is now STALE (>%ds old) — Prometheus is serving "
                    "OUTDATED Sentry metrics until the API recovers",
                    STATS_V2_CACHE_MAX_AGE_SECONDS,
                )
                cls._stale_logged = True
            return

        if cls._consecutive_failures > 0:
            log.warning(
                "collector: Sentry stats_v2 RECOVERED after %d consecutive failure(s); "
                "cache refreshed for %d projects",
                cls._consecutive_failures,
                len(data),
            )
        else:
            log.info("collector: refreshed stats_v2 for %d projects", len(data))
        cls._consecutive_failures = 0
        cls._stale_logged = False

    def _refresh_loop(self):
        """Background loop: refresh the cache every refresh_interval seconds, forever."""
        while True:
            try:
                self._refresh_once()
            except Exception as e:  # never let the refresher thread die
                log.exception("collector: unexpected error in stats_v2 refresh loop: %s", e)
            time.sleep(self.refresh_interval)

    def start_background_refresh(self):
        """Start the daemon refresher thread once per worker process.

        The first refresh runs immediately inside the thread so the cache warms
        within seconds of startup; subsequent refreshes follow the interval.
        """
        with SentryStatsV2Collector._cache_lock:
            if SentryStatsV2Collector._refresher_started:
                return
            SentryStatsV2Collector._refresher_started = True
        thread = threading.Thread(
            target=self._refresh_loop, name="sentry-stats-v2-refresher", daemon=True
        )
        thread.start()
        log.info(
            "collector: started background stats_v2 refresher (interval=%ds)",
            self.refresh_interval,
        )

    def collect(self):
        """Yield stats_v2 metrics from the in-memory cache (never calls Sentry inline)."""

        all_stats_data = self._read_cache()

        org_events_metrics = CounterMetricFamily(
            "sentry_org_events_v2",
            "Event counts per project by category and outcome using stats_v2 API",
            labels=["project_slug", "category", "outcome"],
        )

        quota_exceeded_metrics = GaugeMetricFamily(
            "sentry_quota_exceeded",
            "Number of rate-limited events per project by category (quota exceeded)",
            labels=["project_slug", "category"],
        )

        accepted_events_metrics = GaugeMetricFamily(
            "sentry_accepted_events",
            "Number of accepted events per project by category",
            labels=["project_slug", "category"],
        )

        if all_stats_data:
            for project_slug, categories_data in all_stats_data.items():
                for category, outcomes in categories_data.items():
                    for outcome, count in outcomes.items():
                        org_events_metrics.add_metric(
                            [str(project_slug), str(category), str(outcome)], int(count)
                        )

                    if "rate_limited" in outcomes:
                        quota_exceeded_metrics.add_metric(
                            [str(project_slug), str(category)], int(outcomes["rate_limited"])
                        )

                    if "accepted" in outcomes:
                        accepted_events_metrics.add_metric(
                            [str(project_slug), str(category)], int(outcomes["accepted"])
                        )
            log.debug("collector: served stats for %d projects from cache", len(all_stats_data))
        else:
            log.warning("collector: stats_v2 cache not populated yet, serving empty metrics")

        yield org_events_metrics
        yield quota_exceeded_metrics
        yield accepted_events_metrics

        # Freshness signal: lets alerting distinguish "Sentry data is stale" (a real
        # problem) from "scrape target down" (which no longer happens now that
        # /metrics is served instantly from cache).
        last_success_metric = GaugeMetricFamily(
            "sentry_stats_v2_last_success_timestamp_seconds",
            "Unix timestamp of the last successful stats_v2 fetch from the Sentry API",
        )
        with SentryStatsV2Collector._cache_lock:
            last_success_ts = SentryStatsV2Collector._last_success_ts
        if last_success_ts is not None:
            last_success_metric.add_metric([], last_success_ts)
        yield last_success_metric
