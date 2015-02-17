#!/usr/bin/env python

import time, sys, os
import json
import numpy as np
import glob
from .file_utils import nativepath
from .site_config import get_fileroot, MACRO_FOLDER, LARCH_SCANDB

import larch
from larch.utils import OrderedDict

class LarchScanDBServer(object):
    """
    """
    def __init__(self, scandb, fileroot=None):
        self.scandb = scandb
        self.fileroot = get_fileroot(fileroot)
        self.larch = larch.Interpreter()

        symtab = self.larch.symtable
        symtab.set_symbol(LARCH_SCANDB, self.scandb)
        macro_dir = self.scandb.get_info('macro_folder')
        if macro_dir is None:
            macro_dir = MACRO_FOLDER
            self.scandb.set_info('macro_folder', macro_dir)

        self.macro_dir = macro_dir
        self.loaded_modules = {}
        #self.load_plugins(macro_dir)
        #self.load_modules(macro_dir)

    def load_plugins(self, macro_dir=None):
        if macro_dir is None:
            macro_dir = self.macro_dir
        plugindir = os.path.join(self.fileroot, macro_dir, 'plugins')
        self.larch.symtable._sys.config.plugin_paths.insert(0, plugindir)
        for pyfile in glob.glob(os.path.join(plugindir, '*.py')):
            self.larch.run("add_plugin('%s')" % os.path.split(pyfile)[1][:-3])

    def load_modules(self, macro_dir=None, verbose=False):
        """read latest larch modules"""
        if macro_dir is None:
            macro_dir = self.macro_dir

        moduledir = os.path.join(self.fileroot, macro_dir, 'macros')
        origdir = os.getcwd()
        _sys = self.larch.symtable._sys
        if moduledir not in _sys.path:
            _sys.path.insert(0, moduledir)
        if not os.path.exists(moduledir):
            return

        os.chdir(moduledir)
        for name in glob.glob('*.lar'):
            modname = name[:-4]
            this_mtime = os.stat(name).st_mtime
            if modname in self.loaded_modules:
                last_mtime = self.loaded_modules[modname]
                if this_mtime < last_mtime:
                    continue

            self.larch.error = []
            if verbose:
                print 'importing module: ', modname
            if modname in self.loaded_modules:
                self.larch.run('reload(%s)' % modname)
            else:
                self.larch.run('import %s' % modname)
            if len(self.larch.error) > 0:
                for err in self.larch.error:
                    print '==Import Error %s/%s' % (modname, err.get_error())
            else:
                if modname not in _sys.searchGroups:
                    _sys.searchGroups.append(modname)
                self.loaded_modules[modname] = this_mtime
                thismod  = self.larch.symtable.get_symbol(modname)
                _sys.searchGroupObjects.append(thismod)

        # move back to working folder
        self.scandb.set_path(fileroot=self.fileroot)
        return self.get_macros()

    def __call__(self, arg):
        return self.larch.run(arg)

    def run(self, command):
        self.larch.error = []
        out = self.larch.run(str(command))
        if len(self.larch.error) > 0:
            print 'Error: ', self.larch.error[0].msg
        return out

    def set_symbol(self, name, value):
        self.larch.symtable.set_symbol(name, value)

    def get_symbol(self, name):
        return getattr(self.larch.symtable, name)

    def get_error(self):
        return self.larch.error

    def get_macros(self):
        """return an orderded dictionary of larch functions/procedures
        that are exposed to user for Scan macros

        These are taken from the _epics, _scan, and macros groups

        returned dictionary has function names as keys, and docstrings as values
        """
        macros = OrderedDict()
        symtab = self.larch.symtable
        for group in (symtab._epics, symtab._scan, symtab.macros):
            for name in dir(group):
                obj = getattr(group, name)
                if callable(obj):
                    doc  = obj.__doc__
                    if doc is None:
                        doc = 'PRIVATE'
                        if hasattr(obj, '_signature'):
                            doc = obj._signature()
                    if 'PRIVATE' not in doc:
                        macros[name] = doc
        return macros
