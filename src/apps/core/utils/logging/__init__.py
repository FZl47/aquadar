import logging

_logger = logging.getLogger('root')


def log_event(msg, level='info', exc_info=False, **kwargs):
    level = level.upper()
    levels = {
        'NOTSET': 0,
        'DEBUG': 10,
        'INFO': 20,
        'WARNING': 30,
        'ERROR': 40,
        'CRITICAL': 50,
    }
    logging.log(levels[level], msg=msg, exc_info=exc_info, **kwargs)
