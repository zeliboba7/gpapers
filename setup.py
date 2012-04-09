#!/usr/bin/env python

from distutils.core import setup

setup(name='gPapers',
      version='0.5dev',
      description='The Gnome-based Scientific Paper Organizer',
      author='Derek Anderson',
      author_email='public@kered.org',
      url='http://gpapers.org/',
      packages=['gpapers', 'gpapers.gPapers', 'gpapers.importer', 'deseb'],
      scripts=['gpapers.py'],
      #TODO: Icons, UI files, desktop file
     )
