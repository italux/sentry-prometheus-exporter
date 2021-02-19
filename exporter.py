import logging
from os import getenv
from time import sleep
from wsgiref.simple_server import make_server

from flask import Flask
from prometheus_client import make_wsgi_app, start_http_server
from prometheus_client.core import REGISTRY
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple

from helpers.prometheus import SentryCollector, clean_registry
from libs.sentry import SentryAPI

DEFAULT_BASE_URL = "https://sentry.io/api/0/"
BASE_URL = getenv("SENTRY_BASE_URL") or DEFAULT_BASE_URL
AUTH_TOKEN = getenv("SENTRY_AUTH_TOKEN")
ORG_SLUG = getenv("SENTRY_EXPORTER_ORG")
PROJECTS_SLUG = getenv("SENTRY_EXPORTER_PROJECTS")
LOG_LEVEL = getenv("LOG_LEVEL", "INFO")

log = logging.getLogger("exporter")
level = logging.getLevelName(LOG_LEVEL)
logging.basicConfig(
    level=logging.getLevelName(level),
    format="%(asctime)s - %(process)d - %(levelname)s - %(name)s - %(message)s",
)

app = Flask(__name__)


@app.route("/")
def hello_world():
    return "<h1>Sentry Issues & Events Exporter</h1>\
    <h3>Go to <a href=/metrics/>/metrics</a></h3>\
    "


@app.route("/metrics/")
def sentry_exporter():
    sentry = SentryAPI(BASE_URL, AUTH_TOKEN)
    log.info("exporter: cleaning registry collectors...")
    clean_registry()
    REGISTRY.register(SentryCollector(sentry, ORG_SLUG, PROJECTS_SLUG))
    exporter = DispatcherMiddleware(app.wsgi_app, {"/metrics": make_wsgi_app()})
    return exporter


if __name__ == "__main__":

    if not ORG_SLUG or not AUTH_TOKEN:
        log.error("ENVs: SENTRY_AUTH_TOKEN or SENTRY_EXPORTER_ORG was not found!")
        exit(1)

    log.info("Starting simple wsgi server...")
    # The binding port was picked from the Default port allocations documentation:
    # https://github.com/prometheus/prometheus/wiki/Default-port-allocations
    run_simple(hostname="0.0.0.0", port=9790, application=app.wsgi_app)
