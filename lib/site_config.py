#!/usr/bin/env python

import os
import sys

DARWIN_ROOT  = os.path.join(os.environ.get('HOME', '/') , '.larch')
WINDOWS_ROOT = 'T:/xas_user/'
LINUX_ROOT   = '/cars5/Data/xas_user/'
LARCH_SCANDB = '_scan._scandb'
LARCH_INSTDB = '_scan._instdb'

def get_fileroot(fileroot=None):
    if fileroot is None:
        fileroot = LINUX_ROOT
        if os.name == 'nt':
            fileroot = WINDOWS_ROOT
        elif sys.platform == 'darwin':
            fileroot = DARWIN_ROOT
    return fileroot
