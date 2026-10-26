"""cloudmon - a tiny, dependency-light uptime monitor with automated alerting."""
import logging

__version__ = "1.0.0"

logging.getLogger("cloudmon").addHandler(logging.NullHandler())
