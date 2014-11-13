#!/usr/bin/env python

import os
import sys

DARWIN_ROOT  = '/Volumes/Data/xas_user/'
WINDOWS_ROOT = 'T:/xas_user/'
LINUX_ROOT   = '/cars5/Data/xas_user/'
MACRO_FOLDER  = 'scan_config/13ide'

LARCH_SCANDB = '_scan._scandb'

def get_fileroot(fileroot=None):
    if fileroot is None:
        fileroot = LINUX_ROOT
        if os.name == 'nt':
            fileroot = WINDOWS_ROOT
        elif sys.platform == 'darwin':
            fileroot = DARWIN_ROOT
    return fileroot
    
