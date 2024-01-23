import logging
from os import getenv
from time import sleep
from wsgiref.simple_server import make_server

from flask import Flask
from flask_httpauth import HTTPBasicAuth
from flask_healthz import healthz
from prometheus_client import make_wsgi_app
from prometheus_client.core import REGISTRY
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.security import generate_password_hash, check_password_hash

from helpers.prometheus import SentryCollector, clean_registry
from libs.sentry import SentryAPI

# TODO - Move these settings to use Flask Ccnfiguration Handling
# https://flask.palletsprojects.com/en/2.0.x/config/
DEFAULT_BASE_URL = "https://sentry.io/api/0/"
BASE_URL = getenv("SENTRY_BASE_URL") or DEFAULT_BASE_URL
AUTH_TOKEN = getenv("SENTRY_AUTH_TOKEN")
ORG_SLUG = getenv("SENTRY_EXPORTER_ORG")
PROJECTS_SLUG = getenv("SENTRY_EXPORTER_PROJECTS")
EXPORTER_BASIC_AUTH = getenv("SENTRY_EXPORTER_BASIC_AUTH") or "False"
EXPORTER_BASIC_AUTH_USER = getenv("SENTRY_EXPORTER_BASIC_AUTH_USER") or "prometheus"
EXPORTER_BASIC_AUTH_PASS = getenv("SENTRY_EXPORTER_BASIC_AUTH_PASS") or "prometheus"
LOG_LEVEL = getenv("LOG_LEVEL", "INFO")

log = logging.getLogger("exporter")
gunicorn_error_logger = logging.getLogger("gunicorn.error")
level = logging.getLevelName(LOG_LEVEL)
logging.basicConfig(
    level=logging.getLevelName(level),
    format="[%(asctime)s] [%(process)d] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S %z",
)

app = Flask(__name__)
app.register_blueprint(healthz, url_prefix="/healthz")
app.logger.handlers.extend(gunicorn_error_logger.handlers)

app.config["HEALTHZ"] = {
    "live": "helpers.utils.liveness",
    "ready": "helpers.utils.readiness",
}

auth = HTTPBasicAuth()

users = {
    EXPORTER_BASIC_AUTH_USER: generate_password_hash(EXPORTER_BASIC_AUTH_PASS),
}


def basic_auth_is_enabled(enabled):
    """Convert the human readable boolean to @auth.login_required optional param"""
    if enabled == "True":
        return False
    else:
        return True


@auth.verify_password
def verify_password(username, password):
    """verify that the username and password combination provided by the client are valid"""
    if username in users and check_password_hash(users.get(username), password):
        return username


def get_metric_config():
    """Get metric scraping options."""
    scrape_issue_metrics = getenv("SENTRY_SCRAPE_ISSUE_METRICS") or "True"
    scrape_events_metrics = getenv("SENTRY_SCRAPE_EVENT_METRICS") or "True"
    scrape_rate_limit_metrics = getenv("SENTRY_SCRAPE_RATE_LIMIT_METRICS") or "False"
    default_for_time_metrics = "True" if scrape_issue_metrics == "True" else "False"
    get_1h_metrics = getenv("SENTRY_ISSUES_1H") or default_for_time_metrics
    get_24h_metrics = getenv("SENTRY_ISSUES_24H") or default_for_time_metrics
    get_14d_metrics = getenv("SENTRY_ISSUES_14D") or default_for_time_metrics
    return [
        scrape_issue_metrics,
        scrape_events_metrics,
        scrape_rate_limit_metrics,
        get_1h_metrics,
        get_24h_metrics,
        get_14d_metrics,
    ]


@app.route("/")
def home():
    return "<h1>Sentry Issues & Events Exporter</h1>\
    <h3>Go to <a href=/metrics/>/metrics</a></h3>\
    "


@app.route("/metrics/")
@auth.login_required(optional=basic_auth_is_enabled(EXPORTER_BASIC_AUTH))
def sentry_exporter():
    sentry = SentryAPI(BASE_URL, AUTH_TOKEN)
    log.info("exporter: cleaning registry collectors...")
    clean_registry()
    REGISTRY.register(SentryCollector(sentry, ORG_SLUG, get_metric_config(), PROJECTS_SLUG))
    exporter = DispatcherMiddleware(app.wsgi_app, {"/metrics": make_wsgi_app()})
    return exporter


if __name__ == "__main__":
    if not ORG_SLUG or not AUTH_TOKEN:
        log.error("ENVs: SENTRY_AUTH_TOKEN or SENTRY_EXPORTER_ORG was not found!")
        exit(1)

    log.info("auth: basic authentication enabled: {}".format(EXPORTER_BASIC_AUTH))

    if (
        EXPORTER_BASIC_AUTH == "True"
        and EXPORTER_BASIC_AUTH_USER == "prometheus"
        or EXPORTER_BASIC_AUTH_PASS == "prometheus"
    ):
        log.info("auth: using default username and password.")
    else:
        log.debug(
            'auth: using custom username: "{user}" and password: "{pwd}*******"'.format(
                user=EXPORTER_BASIC_AUTH_USER,
                pwd=EXPORTER_BASIC_AUTH_PASS[
                    # showing only half of the password characters to help debug
                    : len(EXPORTER_BASIC_AUTH_PASS)
                    - int(len(EXPORTER_BASIC_AUTH_PASS) / 2)
                ],
            )
        )
