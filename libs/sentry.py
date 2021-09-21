from datetime import datetime
from os import getenv

from retry import retry
import requests

retry_settings = {
    "tries": int(getenv("SENTRY_RETRY_TRIES", "3")),
    "delay": float(getenv("SENTRY_RETRY_DELAY", "1")),
    "max_delay": float(getenv("SENTRY_RETRY_MAX_DELAY", "10")),
    "backoff": float(getenv("SENTRY_RETRY_BACKOFF", "2")),
    "jitter": float(getenv("SENTRY_RETRY_JITTER", "0.5")),
}


class SentryAPI(object):
    """A simple :class:`SentryAPI <SentryAPI>` to interact with Sentry's Web API.

    Used to interact with Sentry's API to do basic list operations

    Authentication tokens are passed using an auth header, and are used to authenticate
    as a user account with the API.

    Typical usage example:

      >>> from libs.sentry import SentryAPI
      >>> sentry = SentryAPI(BASE_URL, AUTH_TOKEN)
      >>> sentry.organizations()
      [{'id': '7446', 'slug': 'loggi', 'name': 'loggi', 'status': 'active'}]
    """

    def __init__(self, base_url, auth_token):
        """Inits SentryAPI with base sentry's URL and authentication token."""
        super(SentryAPI, self).__init__()
        self.base_url = base_url
        self.__token = auth_token
        self.__session = requests.Session()

    @retry(requests.exceptions.HTTPError, **retry_settings)
    def __get(self, url):
        HEADERS = {"Authorization": "Bearer " + self.__token}
        response = self.__session.get(self.base_url + url, headers=HEADERS)
        response.raise_for_status()
        return response

    def __post(self, url):
        raise NotImplementedError

    def organizations(self):
        """Return a list of organizations."""

        resp = self.__get("organizations/")
        organizations = []
        for org in resp.json():
            organization = {}
            organization.update(
                {
                    "id": org.get("id"),
                    "slug": org.get("slug"),
                    "name": org.get("name"),
                    "status": org.get("status").get("id"),
                }
            )
            organizations.append(organization)

        return organizations

    def get_org(self, org_slug):
        """Return a organization details.

        Return details on an individual organization including
        various details such as membership access, features, and teams.

        Args:
            org_slug: A organization's slug string name.

        Returns:
            A dict mapping keys to the corresponding organization
        """

        resp = self.__get("organizations/{org}/".format(org=org_slug))
        org = resp.json()
        organization = {}
        organization.update(
            {
                "id": org.get("id"),
                "slug": org.get("slug"),
                "name": org.get("name"),
                "status": org.get("status"),
                "platform": org.get("platform"),
            }
        )

        return organization

    def projects(self):
        """Return a list of projects available to the authenticated session.

        Returns:
            A list mapping with dictionary keys to the corresponding projects
        """

        resp = self.__get("projects/")
        projects = []
        for proj in resp.json():
            project = {}
            project.update(
                {
                    "id": proj.get("id"),
                    "slug": proj.get("slug"),
                    "name": proj.get("name"),
                    "status": proj.get("status"),
                    "platform": proj.get("platform"),
                }
            )
            projects.append(project)

        return projects

    def get_project(self, org_slug, project_slug):
        """Return details on an individual project.

        Args:
            org_slug: A organization's slug string name.
            project_slug: The project's slug string name

        Returns:
            A dict mapping keys to the corresponding project
        """

        resp = self.__get(
            "projects/{org}/{proj_slug}/".format(org=org_slug, proj_slug=project_slug)
        )
        proj = resp.json()
        project = {}
        project.update(
            {
                "id": proj.get("id"),
                "slug": proj.get("slug"),
                "name": proj.get("name"),
                "status": proj.get("status"),
                "platform": proj.get("platform"),
            }
        )

        return project

    def project_stats(self, org_slug, project_slug):
        """Retrieve event counts for a project

        Return a set of points representing a normalized timestamp
        and the number of events seen in the period.

        Query ranges are limited to Sentry's configured time-series resolutions.

        Args:
            org_slug: A organization's slug string name.
            project_slug: The project's slug string name

        Returns:
            A dict([list])
        """

        events = 0
        first_day_month = datetime.timestamp(datetime.today().replace(day=1))
        today = datetime.timestamp(datetime.today())
        stat_names = ["received", "rejected", "blacklisted"]
        stats = {}
        project_events = {}

        for stat_name in stat_names:
            resp = self.__get(
                "projects/{org}/{proj_slug}/stats/?stat={stat}&since={since}&until={until}".format(
                    org=org_slug,
                    proj_slug=project_slug,
                    stat=stat_name,
                    since=first_day_month,
                    until=today,
                )
            )
            stats[stat_name] = resp.json()

        for stat_name, values in stats.items():
            for stat in values:
                if type(stat) != str:
                    events += stat[1]
            project_events[stat_name] = events

        return project_events

    def environments(self, org_slug, project):
        """Return a list of project's environments.

        Args:
            org_slug: A organization slug string name.
            project: dict instance of a project.

        Returns:
            A list mapping with all project's corresponding issues and each element is a dict.

        Raises:
            TypeError: An error occurred if the project instance isn't a valid dict
        """

        if not isinstance(project, dict):
            raise TypeError("project param isn't a dictionary")

        resp = self.__get(
            "projects/{org}/{proj_slug}/environments/".format(
                org=org_slug, proj_slug=project.get("slug")
            ),
        )
        if resp.status_code == 404:
            return []
        environments = [env.get("name") for env in resp.json()]
        return environments

    def issues(self, org_slug, project, environment=None, age="24h"):
        """Return a list open issues to a project.

        Retrieves the first 100 new open issues created in the past age, using the default query
        (i.e.: is:unresolved) sorted by Last Seen events

        Args:
            org_slug: A organization slug string name.
            project: dict instance of a project.
            environments: Optional;
                A sequence of strings representing the environment names.
            age: Optional;
                If age is different from default (aka 24h) query will use now - age.

        Returns:
            A list mapping with all project's corresponding issues and each element is a dict.

        Raises:
            TypeError: An error occurred if the project instance isn't a valid dict
        """

        if not isinstance(project, dict):
            raise TypeError("project param isn't a dictionary")

        issues_url = "projects/{org}/{proj_slug}/issues/?project={proj_id}&sort=date&query=age%3A-{age}".format(
            org=org_slug,
            proj_slug=project.get("slug"),
            proj_id=project.get("id"),
            age=age,
        )

        if environment:
            issues = {}
            issues_url = issues_url + "&environment={env}".format(env=environment)
            resp = self.__get(issues_url)
            if resp.status_code == 404:
                issues[environment] = []
            else:
                issues[environment] = resp.json()
            return issues
        else:
            resp = self.__get(issues_url)
            return {"all": resp.json()}

    def events(self, org_slug, project, environment=None):
        """Return a list of events bound to a project.

        Retrieves the first 100 new events, using the default query sorted by Last Seen events

        Args:
            org_slug: A organization slug string name.
            project: dict instance of a project.
            environments: Optional;
                A sequence of strings representing the environment names.

        Returns:
            A list mapping with all project's corresponding events and each element is a dict.

        Raises:
            TypeError: An error occurred if the project instance isn't a valid dict
        """

        if not isinstance(project, dict):
            raise TypeError("project param isn't a dictionary")

        events_url = "projects/{org}/{proj_slug}/events/?project={proj_id}&sort=date".format(
            org=org_slug, proj_slug=project.get("slug"), proj_id=project.get("id")
        )
        if environment:
            events = {}
            events_url = events_url + "&environment={env}".format(env=environment)
            resp = self.__get(events_url)
            events[environment] = resp.json()
            return events
        else:
            resp = self.__get(events_url)
            return {"all": resp.json()}

    def issue_events(self, issue_id, environment=None):
        """This methid lists issue's events."""

        issue_events_url = "issues/{issue_id}/events/".format(issue_id=issue_id)

        if environment:
            issue_events = {}
            issue_events_url = issue_events_url + "&environment={env}&sort=date".format(
                env=environment
            )
            resp = self.__get(issue_events_url)
            issue_events[environment] = resp.json()
            return issue_events
        else:
            resp = self.__get(issue_events_url)
            return {"all": resp.json()}

    def issue_release(self, issue_id, environment=None):
        """This methid lists issue's events."""

        issue_release_url = "issues/{issue_id}/current-release/".format(issue_id=issue_id)

        if environment:
            issue_release_url = issue_release_url + "?environment={env}".format(env=environment)
            resp = self.__get(issue_release_url)
            curr_release = resp.json().get("currentRelease")
            if curr_release:
                release = curr_release.get("release").get("version")
                return release
            else:
                return curr_release
        else:
            resp = self.__get(issue_release_url)
            release = resp.json().get("currentRelease").get("release").get("version")
            return release

    def project_releases(self, org_slug, project, environment=None):
        """Return a list of releases for a given project into the organization.

        Args:
            org_slug: A organization slug string name.
            project: dict instance of a project.
            environments: Optional;
                A sequence of strings representing the environment names.

        Returns:
            A list mapping with all project's corresponding release and each element is a dict.

        Raises:
            TypeError: An error occurred if the project instance isn't a valid dict
        """

        if not isinstance(project, dict):
            raise TypeError("project param isn't a dictionary")

        proj_releases_url = "organizations/{org}/releases/?project={proj_id}&sort=date".format(
            org=org_slug, proj_id=project.get("id")
        )

        if environment:
            proj_releases = {}
            proj_releases_url = proj_releases_url + "&environment={env}".format(env=environment)
            resp = self.__get(proj_releases_url)
            proj_releases[environment] = resp.json()
            return proj_releases
        else:
            resp = self.__get(proj_releases_url)
            return {"all": resp.json()}
