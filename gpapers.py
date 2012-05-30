#!/usr/bin/python

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

'''
Simple script for starting gpapers. Will do some checking for Python version
and available paths in the future.
'''

import sys

try:
    import gpapers
except ImportError:
    print >> sys.stderr, 'ERROR: Could not find gpapers module files in path:'
    print >> sys.stderr, ' '.join(map(str, sys.path))
    sys.exit(1)

# Start gpapers
gpapers.main(sys.argv)
