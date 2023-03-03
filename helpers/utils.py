import json
import logging
import os.path
from datetime import datetime
from flask_healthz import HealthError
from libs.sentry import SentryAPI
from os import getenv

# TODO - Move these settings to use Flask Ccnfiguration Handling
# https://flask.palletsprojects.com/en/2.0.x/config/
DEFAULT_BASE_URL = "https://sentry.io/api/0/"
BASE_URL = getenv("SENTRY_BASE_URL") or DEFAULT_BASE_URL
AUTH_TOKEN = getenv("SENTRY_AUTH_TOKEN")

log = logging.getLogger(__name__)


def write_cache(filename, data, expire_timestamp=None):
    """Store OAuth token into a local file using pickle"""

    if not isinstance(data, dict):
        raise TypeError("project param isn't a dictionary")

    data.update({"expire_at": expire_timestamp})
    json.dump(data, open(filename, "w"))


def get_cached(filename):
    """Validate if we already have a local token stored, if doesn't initiate the oauth workflow"""
    if os.path.isfile(filename):
        try:
            cache = json.load(open(filename, "r"))
        except json.decoder.JSONDecodeError:
            return False
        if cache.get("expire_at") <= datetime.timestamp(datetime.now()):
            log.debug("cache: expired data, removing cache file: {file}".format(file=filename))
            return False
        return cache
    else:
        return False


def liveness():
    """Return True if the application is running properly"""
    return True  # TODO - Can't find a good way to validate if the app is running properly


def readiness():
    """Return SentryAPI instance saying that app is ready to serve requests"""
    try:
        SentryAPI(BASE_URL, AUTH_TOKEN)
    except Exception as e:
        raise HealthError(e)
