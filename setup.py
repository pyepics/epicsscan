#!/usr/bin/env python

from setuptools import setup

deps = ('wx', 'epics', 'numpy', 'matplotlib', 'psycopg2')

setup(name = 'epicsscan',
      version = '0.5',
      author = 'Matthew Newville',
      author_email = 'newville@cars.uchicago.edu',
      license = 'BSD',
      description = 'Epics Scanning library and applications',
      package_dir = {'epicsscan': 'lib'},
      packages = ['epicsscan', 'epicsscan.server', 'epicsscan.gui',
                  'epicsscan.detectors', 'epicsscan.xps'],
      )

errmsg = "WARNING: epicsscan requires Python module: '%s'"
for mod in deps:
    try:
        a = __import__(mod)
    except ImportError:
        print( errmsg % mod)
