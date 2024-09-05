#!/usr/bin/env python
"""
Macro Kernel for EpicsScan
"""
import time, sys, os
import json
import numpy as np
import glob
from pathlib import Path

from .file_utils import nativepath
from .utils import plain_ascii
from .scandb import ScanDB, InstrumentDB

from asteval import Interpreter
from asteval.astutils import Procedure

from . import macros_init

class MessageWriter(object):
    """Message Writer for MacrosKernel:
    this writes to both stdout and the messages table of scandb.
    """
    def __init__(self, scandb=None, writer=None):
        self.scandb = scandb
        self.writer = writer
        if writer is None:
            self.writer = sys.stdout

    def write(self, text, color=None, bkg=None, **kws):
        """write text to writer
        write('hello', color='red', bkg='grey', bold=True, blink=True)
        """
        attrs = []
        self.writer.write(text)
        if self.scandb is not None:
            self.scandb.set_message(text)

    def flush(self):
        self.writer.flush()
        if self.scandb is not None:
            self.scandb.commit()

class MacroKernel(object):
    """
    Asteval Engine for Macros within EpicsScan
    """
    def __init__(self, scandb=None, load_macros=True):
        if scandb is None:
            scandb = ScanDB()
        self.scandb = scandb
        self.instdb = InstrumentDB(self.scandb)
        self.writer = MessageWriter(scandb=scandb)

        self.fileroot = self.scandb.get_info('server_fileroot')
        self.macrodir = self.scandb.get_info('macro_folder')
        self.macros = {}

        # take all symbols from macros_init, add, _scandb, _instdb,
        # and add some scanning primitives
        syms = {s: getattr(macros_init, s) for s in macros_init.__all__}

        syms['_scandb'] = self.scandb
        syms['_instdb'] = self.instdb

        readonly = [s for s in syms]

        self.eval = Interpreter(user_symbols=syms,
                                readonly_symbols=readonly,
                                builtins_readonly=True,
                                writer=self.writer,
                                err_writer=self.writer,
                                with_import=True,
                                with_importfrom=True)

        if load_macros:
            self.load_macros()

    def check_abort_pause(self, msg='at caget'):
        if self.scandb.test_abort(msg):
            return False
        self.scandb.wait_for_pause(timeout=86400.0)
        return True


    def load_macros(self, macrodir=None, verbose=False):
        """read latest macros"""
        if macrodir is None:
            macrodir = self.macrodir

        root = self.fileroot
        if os.name == 'nt':
            root = self.scandb.get_info('windows_fileroot')
        if root.endswith('/'):
            root = root[:-1]

        macpath = Path(root, macrodir).absolute()
        macpathname = macpath.as_posix()
        if not macpath.exists():
            self.scandb.set_info('scan_message',
                f"Cannot locate modules in '{macpathname}'")
            print(f"no macros imported from {macpathname}")
            return
        try:
            origdir = os.getcwd()
            os.chdir(macpathname)
            for name in glob.glob('*.lar') + glob.glob('*.py'):
                self.eval.error = []
                if verbose:
                    print('importing macros from : ', name)
                fname = Path(macpathname, name).absolute().as_posix()
                with open(name, 'r') as fh:
                    text = fh.read()
                self.eval(text, show_errors=False)
                if len(self.eval.error) > 0:
                    exc, emsg = self.eval.error[0].get_error()

                    msg = '\n'.join(emsg.split('\n')[-1:])
                    msg =f"Macro Import Error: '{fname}'\n{msg}\n"
                    self.scandb.set_info('error_message', msg)
                    print(msg)

            os.chdir(origdir)
        except OSError:
            print("error loading macros")
        self.scandb.set_workdir()
        self.macros = self.get_macros()
        print(f"Loaded {len(self.macros)} macro functions from {macpathname}")

    def __call__(self, arg):
        return self.run(arg)

    def run(self, command=None):
        self.eval.error = []
        return self.eval(plain_ascii(command))

    def set_symbol(self, name, value):
        self.eval.symtable[name] = value

    def get_symbol(self, name):
        return self.eval.symtable.get(name)

    def get_error(self):
        return self.eval.error

    def get_macros(self):
        """return an orderded dictionary of functions/procedures
        that are exposed to user for Scan macros

        returned dictionary has function names as keys, and docstrings as values
        """
        macros = {}
        symtab = self.eval.symtable
        for name, val in self.eval.symtable.items():
            if isinstance(val, Procedure):
                docstring = val._getdoc()
                if docstring is None:
                    docstring = ''
                sig = getattr(val, '_signature', None)
                if callable(sig):
                    sig = sig()
                if 'PRIVATE' not in docstring:
                    macros[name] = sig, docstring, val
        return macros
