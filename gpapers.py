#!/usr/bin/env python
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
