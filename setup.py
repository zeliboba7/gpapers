#! /usr/bin/python

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

import os
from distutils.core import setup
from distutils.command.build_scripts import build_scripts as build_scripts_class

from gpapers import __version__

class gpapers_build_scripts_class(build_scripts_class):
    # Adjust bin/gpapers.py --> gpapers
    # (adapted from code in zim written by Jaap Karssenberg: zim-wiki.org )

    def run(self):
        build_scripts_class.run(self)
        if os.name == 'posix' and not self.dry_run:
            for script in self.scripts:
                fname, ext = os.path.splitext(script)
                if ext == '.py':
                    file = os.path.join(self.build_dir, script)
                    file_no_ext = os.path.join(self.build_dir, fname)
                    print 'renaming %s to %s' % (file, file_no_ext)
                    os.rename(file, file_no_ext)

dependencies = ['gi.repository.Gtk',
                'gi.repository.GdkPixbuf',
                'gi.repository.Pango',
                'gi.repository.Poppler',
                'django',
                'gi.repository.Soup'
                'BeautifulSoup',
                'feedparser',
                'pdfminer'] 

setup(name='gPapers',
      cmdclass={'build_scripts': gpapers_build_scripts_class},
      version=__version__,
      description='The Gnome-based Scientific Paper Organizer',
      author='Derek Anderson <public@kered.org>, Marcel Stimberg <marcelcoding@googlemail.com>',
      author_email='gpapers-discuss@googlegroups.com',
      url='http://gpapers.org/',
      packages=['gpapers', 'gpapers.gPapers', 'gpapers.importer'],
      package_data={'gpapers': ['data/*', 'icons/*']},
      data_files=[('share/applications', ['xdg/gpapers.desktop'])],
      scripts=['gpapers.py'],
      classifiers=[
          'Development Status :: 3 - Alpha',
          'Environment :: X11 Applications :: GTK',
          'Intended Audience :: End Users/Desktop',
          'Intended Audience :: Science/Research',
          'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
          'Operating System :: POSIX :: Linux',
          'Programming Language :: Python',
          'Topic :: Utilities'
          ],
      requires=dependencies
     )
