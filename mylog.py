import logging
import logging.handlers
import sys


def get_logger(
    name,
    level=logging.INFO,
    console=True,
    logfile=None,
    syslog=False,
    fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
):
    log = logging.getLogger(name)
    log.setLevel(level)
    log.propagate = False

    if log.handlers:
        return log

    formatter = logging.Formatter(fmt, datefmt=datefmt)

    if console:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(formatter)
        log.addHandler(h)

    if logfile:
        h = logging.FileHandler(logfile)
        h.setFormatter(formatter)
        log.addHandler(h)

    if syslog:
        h = logging.handlers.SysLogHandler(address="/dev/log")
        h.setFormatter(logging.Formatter(
            "%(name)s: %(levelname)s %(message)s"
        ))
        log.addHandler(h)

    return log

