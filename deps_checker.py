import os, sys

RUN_FROM_DIR = os.path.abspath(os.path.dirname(sys.argv[0])) + '/'

try:
  import sqlite3
except:
  try:
    from pysqlite2 import dbapi2 as sqlite3
  except:
    #traceback.print_exc()
    print 'could not import required sqlite3 libraries.  try running:'
    print '\tfor ubuntu or debian: sudo apt-get install python-sqlite3'
    print '\tfor redhat: yum install python-sqlite3'
    print 'note that if your distro doesn\'t have python-sqlite3 yet, you can use pysqlite2'
    sys.exit()

try:
  from django.template import defaultfilters
  print 
  print 'note: django provides a web-based administrative tool for your database.  to use it, uncomment the commented-out lines under INSTALLED_APPS in settings.py and run the following:'
  print '     ./manage.py runserver'
  print '    then go to http://127.0.0.1:8000/admin/'
  print
except:
  print 'could not import django [http://www.djangoproject.com/]. Try running  ',
  print '\tsudo apt-get install python-django'
  sys.exit()
  
try:
  import cairo
except:
  #traceback.print_exc()
  print 'could not import pycairo [http://cairographics.org/pycairo/]. Try running:' % RUN_FROM_DIR
  print '\tsudo apt-get install python-cairo'

try:
  import poppler
except:
  #traceback.print_exc()
  print 'could not import pypoppler [http://poppler.freedesktop.org/]. Try running:' % RUN_FROM_DIR
  print '\tsudo apt-get install python-poppler'


