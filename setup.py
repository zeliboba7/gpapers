#!/usr/bin/env python

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
