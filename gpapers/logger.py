'''
Logging information for gPapers
'''

#    gPapers
#    Copyright (C) 2007-2009 Derek Anderson
#                  2012      Derek Anderson and Marcel Stimberg
#
# This file is part of gPapers.
#
#    gPapers is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    gPapers is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with gPapers.  If not, see <http://www.gnu.org/licenses/>.

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
