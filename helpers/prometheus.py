import logging
import concurrent.futures
from datetime import datetime, timedelta
from uuid import uuid4

from prometheus_client.core import (
    REGISTRY,
    CounterMetricFamily,
    GaugeHistogramMetricFamily,
    GaugeMetricFamily,
)

from helpers.utils import get_cached, write_cache

# constants for caching file
JSON_CACHE_FILE = "/tmp/sentry-prometheus-exporter-cache.json"
DEFAULT_CACHE_EXPIRE_TIMESTAMP = int(datetime.timestamp(datetime.now() + timedelta(minutes=2)))

log = logging.getLogger(__name__)


def clean_registry():
    # Loop with try except to remove all default collectors
    for _, collector in list(REGISTRY._names_to_collectors.items()):
        try:
            REGISTRY.unregister(collector)
        except KeyError:
            pass


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
        max_collector_worker=5
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
        self.max_collector_worker = max_collector_worker

    def __get_project_and_envs_from_project_slug(self, project_slug, projects, projects_slug, projects_envs):
        log.debug(
            "metadata: getting {proj} project data from API".format(proj=project_slug)
        )
        project = self.__sentry_api.get_project(self.org.get("slug"), project_slug)
        projects.append(project)
        projects_slug.append(project_slug)
        envs = self.__sentry_api.environments(self.org.get("slug"), project)
        projects_envs[project.get("slug")] = envs

    def __get_project_and_envs(self, projects, project, projects_slug, projects_envs):
        log.debug(
            "metadata: getting projects and its envs data from API"
        )
        projects.append(project)
        projects_slug.append(project.get("slug"))
        envs = self.__sentry_api.environments(self.org.get("slug"), project)
        projects_envs[project.get("slug")] = envs

    def __get_project_env_issue_metrics(self, project, env, projects_issue_data):
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

    def __build_sentry_data_from_api(self, thread_executor=None):
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

        assert thread_executor is not None

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
            __future_get_project_and_envs_from_project_slug = set()
            for project_slug in self.sentry_projects_slug.split(","):
                 __future_get_project_and_envs_from_project_slug.add(
                    thread_executor.submit(
                        self.__get_project_and_envs_from_project_slug,
                        project_slug,
                        projects,
                        projects_slug,
                        projects_envs
                    )
                )
            finished_tasks, unfinished_tasks = concurrent.futures.wait(
                __future_get_project_and_envs_from_project_slug,
                return_when=concurrent.futures.FIRST_EXCEPTION
            )
            for finished_task in finished_tasks:
                err = finished_task.exception()
                if err is not None:
                    raise err

            log.info(
                "metadata: projects loaded from API: {num_proj}".format(num_proj=len(projects))
            )
        else:
            log.info(
                "metadata: no projects specified, loading from API".format(num_proj=len(projects))
            )
            __future_get_project_and_envs = set()
            for project in self.__sentry_api.projects(self.sentry_org_slug):
                __future_get_project_and_envs.add(
                    thread_executor.submit(
                        self.__get_project_and_envs,
                        projects,
                        project,
                        projects_slug,
                        projects_envs
                    )
                )
            finished_tasks, unfinished_tasks = concurrent.futures.wait(
                __future_get_project_and_envs,
                return_when=concurrent.futures.FIRST_EXCEPTION
            )
            for finished_task in finished_tasks:
                err = finished_task.exception()
                if err is not None:
                    raise err
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

            __future_get_project_env_issue_metrics = set()
            for project in __metadata.get("projects"):
                projects_issue_data[project.get("slug")] = {}
                envs = __metadata.get("projects_envs").get(project.get("slug"))
                for env in envs:
                    __future_get_project_env_issue_metrics.add(
                        thread_executor.submit(
                            self.__get_project_env_issue_metrics,
                            project,
                            env,
                            projects_issue_data
                        )
                    )
            finished_tasks, unfinished_tasks = concurrent.futures.wait(
                __future_get_project_env_issue_metrics,
                return_when=concurrent.futures.FIRST_EXCEPTION
            )
            for finished_task in finished_tasks:
                err = finished_task.exception()
                if err is not None:
                    raise err

            data["projects_data"] = projects_issue_data

        write_cache(JSON_CACHE_FILE, data, DEFAULT_CACHE_EXPIRE_TIMESTAMP)
        log.debug("cache: writing data structure to file: {cache}".format(cache=JSON_CACHE_FILE))
        return data

    def __build_sentry_data(self, thread_executor=None):
        assert thread_executor is not None

        data = get_cached(JSON_CACHE_FILE)

        if data is False:
            log.debug("cache: {cache} not found.".format(cache=JSON_CACHE_FILE))
            log.debug("cache: rebuilding from API...")
            api_data = self.__build_sentry_data_from_api(thread_executor=thread_executor)
            return api_data

        log.debug("cache: reading data structure from file: {cache}".format(cache=JSON_CACHE_FILE))
        return data

    def __get_rate_limit_second(self, project, project_rate_metrics):
        rate_limit_second = self.__sentry_api.rate_limit(
            self.org.get("slug"), project.get("slug")
        )
        project_rate_metrics.add_metric(
            [str(project.get("slug"))], round(rate_limit_second, 6)
        )

    def __get_project_stats(self, project, project_events_metrics):
        events = self.__sentry_api.project_stats(self.org.get("slug"), project.get("slug"))
        for stat, value in events.items():
            project_events_metrics.add_metric(
                [
                    str(project.get("slug")),
                    str(stat),
                ],
                int(value),
            )

    def __get_issue_release(self, issue, env, issues_metrics):
        release = self.__sentry_api.issue_release(issue.get("id"), env)
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
                        datetime.strptime(
                            str(
                                issue.get("firstSeen")
                                # if the issue age is recent, firstSeen returns None
                                # and we'll return datetime.now() as default
                                or datetime.strftime(
                                    datetime.now(), "%Y-%m-%dT%H:%M:%SZ"
                                )
                            ),
                            "%Y-%m-%dT%H:%M:%SZ",
                        ),
                        "%Y-%m-%d",
                    )
                ),
                str(
                    datetime.strftime(
                        datetime.strptime(
                            str(
                                issue.get("lastSeen")
                                # if the issue age is recent, lastSeen returns None
                                # and we'll return datetime.now() as default
                                or datetime.strftime(
                                    datetime.now(), "%Y-%m-%dT%H:%M:%SZ"
                                )
                            ),
                            "%Y-%m-%dT%H:%M:%SZ",
                        ),
                        "%Y-%m-%d",
                    )
                ),
            ],
            int(issue.get("count")),
        )

    def collect(self):
        """Yields metrics from the collectors in the registry."""

        # multithread processing so that we can collect metrics faster
        # on organization that has many projects and issues.
        __thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_collector_worker)
        __data = self.__build_sentry_data(thread_executor=__thread_executor)
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
                        histo_buckets.append(("14d", float(events_14d)))
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
                for env in envs:
                    project_issues_1h = project_issues.get(env).get("1h")
                    __future_get_issue_release = set()
                    for issue in project_issues_1h:
                        __future_get_issue_release.add(
                            __thread_executor.submit(
                                self.__get_issue_release,
                                issue,
                                env,
                                issues_metrics,
                            )
                        )
                    finished_tasks, unfinished_tasks = concurrent.futures.wait(
                        __future_get_issue_release,
                        return_when=concurrent.futures.FIRST_EXCEPTION
                    )
                    for finished_task in finished_tasks:
                        err = finished_task.exception()
                        if err is not None:
                            raise err
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

            __future_get_project_stats = set()
            for project in __metadata.get("projects"):
                __future_get_project_stats.add(
                    __thread_executor.submit(
                        self.__get_project_stats,
                        project,
                        project_events_metrics,
                    )
                )
            finished_tasks, unfinished_tasks = concurrent.futures.wait(
                __future_get_project_stats,
                return_when=concurrent.futures.FIRST_EXCEPTION
            )
            for finished_task in finished_tasks:
                err = finished_task.exception()
                if err is not None:
                    raise err

            yield project_events_metrics

        if self.rate_limit_metrics == "True":
            project_rate_metrics = GaugeMetricFamily(
                "sentry_rate_limit_events_sec",
                "Rate limit events per second for a project",
                labels=["project_slug"],
            )

            __future_get_rate_limit_second = set()
            for project in __metadata.get("projects"):
                __future_get_rate_limit_second.add(
                    __thread_executor.submit(
                        self.__get_rate_limit_second,
                        project,
                        project_rate_metrics,
                    )
                )
            finished_tasks, unfinished_tasks = concurrent.futures.wait(
                __future_get_rate_limit_second,
                return_when=concurrent.futures.FIRST_EXCEPTION
            )
            for finished_task in finished_tasks:
                err = finished_task.exception()
                if err is not None:
                    raise err

            yield project_rate_metrics
