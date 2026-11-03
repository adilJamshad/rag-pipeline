from contextlib import contextmanager

import psycopg

from . import config


@contextmanager
def connect():
    with psycopg.connect(config.DATABASE_URL) as conn:
        yield conn
