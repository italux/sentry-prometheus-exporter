import json
import logging
import os.path
from datetime import datetime

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
        cache = json.load(open(filename, "r"))
        if cache.get("expire_at") <= datetime.timestamp(datetime.now()):
            log.debug("cache: expired data, removing cache file: {file}".format(file=filename))
            return False
        return cache
    else:
        return False
