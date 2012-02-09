'''
Logging information for Brian
'''

import logging
import sys

__all__ = ['log_error', 'log_warn', 'log_info', 'log_debug', 'log_level_error',
           'log_level_warn', 'log_level_info', 'log_level_debug' ]

console = logging.StreamHandler(sys.stderr)
formatter = logging.Formatter('%(asctime)s: %(name)-18s: %(levelname)-8s %(message)s')
console.setFormatter(formatter)
logging.getLogger('gPapers').addHandler(console)

def log_error(message):
    logging.getLogger('gPapers').error(message)

def log_warn(message):
    logging.getLogger('gPapers').warn(message)

def log_info(message):
    logging.getLogger('gPapers').info(message)

def log_debug(message):
    logging.getLogger('gPapers').debug(message)

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