'''
Logging information for Brian
'''

import logging
import sys

__all__ = ['log_error', 'log_warn', 'log_info', 'log_debug', 'log_level_error',
           'log_level_warn', 'log_level_info', 'log_level_debug' ]

console = logging.StreamHandler(sys.stderr)
formatter = logging.Formatter('%(name)-18s: %(levelname)-8s %(message)s')
console.setFormatter(formatter)
logging.getLogger('gPapers').addHandler(console)

get_log = logging.getLogger

def log_error(logname, message):
    get_log(logname).error(message)

def log_warn(logname, message):
    get_log(logname).warn(message)

def log_info(logname, message):
    get_log(logname).info(message)

def log_debug(logname, message):
    get_log(logname).debug(message)

def log_level_error():
    '''Shows log messages only of level ERROR or higher.
    '''
    logging.getLogger('gPapers').setLevel(logging.ERROR)

def log_level_warn():
    '''Shows log messages only of level WARNING or higher (including ERROR
    level).
    '''
    logging.getLogger('gPapers').setLevel(logging.WARN)

def log_level_info():
    '''Shows log messages only of level INFO or higher (including WARNING and
    ERROR levels).
    '''
    logging.getLogger('gPapers').setLevel(logging.INFO)

def log_level_debug():
    '''Shows log messages only of level DEBUG or higher (including INFO,
    WARNING and ERROR levels).
    '''
    logging.getLogger('gPapers').setLevel(logging.DEBUG)