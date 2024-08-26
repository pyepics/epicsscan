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

from . import macros_init

macro_syms = ['caget', 'caput', 'get_pv', 'PV', 'consts', 'etok', 'ktoe',
              'AMU', 'ATOM_NAMES', 'ATOM_SYMS', 'AVOGADRO', 'DEG2RAD',
              'E_MASS', 'PI', 'PLANCK_HBARC', 'PLANCK_HC', 'RAD2DEG',
              'RYDBERG', 'R_ELECTRON_ANG', 'R_ELECTRON_CM', 'SI_PREFIXES',
              'TAU', 'XAFS_KTOE', 'atomic_density', 'atomic_mass',
              'atomic_name', 'atomic_number', 'atomic_symbol', 'chemparse',
              'core_width', 'darwin_width', 'f0', 'f1_chantler', 'f2_chantler',
              'fluor_yield', 'get_material', 'guess_edge', 'index_nearest',
              'index_of', 'ionchamber_fluxes', 'ionization_potential',
              'material_mu', 'material_mu_components', 'mirror_reflectivity',
              'mu_elam', 'xray_delta_beta', 'xray_edge', 'xray_edges',
              'xray_line', 'xray_lines']


scan_primitives = '''
def scan_from_db(scanname, filename="scan.001"):
    """
    get scan definition from ScanDB by name
    """
    try:
        scan = _scandb.make_scan(scanname)
        scan.filename = filename
    except ScanDBException:
        raise ScanDBException(f"no scan definition '{scanname}' found")
    return scan

def do_scan(scanname, filename="scan.001", nscans=1, comments=""):
    """do_scan(scanname, filename="scan.001", nscans=1, comments="")

    execute a step scan as defined in Scan database

    Parameters
    ----------
    scanname:     string, name of scan
    filename:     string, name of output data file
    comments:     string, user comments for file
    nscans:       integer (default 1) number of repeats to make.

    Examples
    --------
      do_scan("cu_xafs", "cu_sample1.001", nscans=3)

    Notes
    ------
      1. The filename will be incremented so that each scan uses a new filename.
    """
    global _scandb
    if _scandb is None:
        print("do_scan: need to connect to scandb!")
        return
    if nscans is not None:
        _scandb.set_info("nscans", nscans)

    scan = scan_from_db(scanname, filename=filename)
    scan.comments = comments
    if scan.scantype == "slew":
        return scan.run(filename=filename, comments=comments)
    else:
        scans_completed = 0
        nscans = int(_scandb.get_info("nscans"))
        abort  = _scandb.get_info("request_abort", as_bool=True)
        while (scans_completed  < nscans) and not abort:
            scan.run()
            scans_completed += 1
            nscans = int(_scandb.get_info("nscans"))
            abort  = _scandb.get_info("request_abort", as_bool=True)
        return scan

def get_dbinfo(key, default=None, as_bool=False, as_int=False, full_row=False):
    """get a value for a keyword in the scan info table,
    where most status information is kept.

    Arguments
    ---------
     key        name of data to look up
     default    (default None) value to return if key is not found
     as_bool    (default False) convert to bool
     as_int     (default False) convert to int
     full_row   (default False) return full row, not just value

    Notes
    -----
     1.  if this key doesn"t exist, it will be added with the default
         value and the default value will be returned.
     2.  the full row will include notes, create_time, modify_time

    """
    return _scandb.get_info(key, default=default, full_row=full_row,
                            as_int=as_int, as_bool=as_bool)

def set_dbinfo(key, value, notes=None, **kws):
    """set a value for a keyword in the scan info table."""
    return _scandb.set_info(key, value, notes=notes)

de check_scan_abort():
    """returns whether Abort has been requested"""
    return get_dbinfo('request_abort', as_bool=True)

def move_instrument(inst_name, position_name, wait=True, timeout=60.0):
    """move an Epics Instrument to a named position

    Parameters:
        inst_name (string): name of Epics Instrument
        position_name (string):  name of position for the Instrument
        wait (True or False): whether to wait for move to complete [True]
        timeout (float): time in seconds to give up waiting [60]

    Examples:
        move_instrument('Double H Mirror Stripes', 'platinum', wait=True)

    """
    _instdb.restore_position(inst_name, position_name, wait=wait, timeout=timeout)

def move_samplestage(position_name, wait=True, timeout=60.0):
    """move Instrument for Samplestage to a named position

    Parameters:
        position_name (string):  name of sample position
        wait (True or False): whether to wait for move to complete [True]
        timeout (float): time in seconds to give up waiting [60]

    Notes:
         the instrument for the sample will be fetched from
             _scandb.get_info('samplestage_instrument')

    Examples:
        move_sample('Map1 positionA', wait=True)

    """
    inst_name = _scandb.get_info('samplestage_instrument')
    _instdb.restore_position(inst_name, position_name, wait=wait, timeout=timeout)
'''


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
    def __init__(self, scandb=None):
        if scandb is Non:
            scandb = ScanDB()
        self.scandb = scandb
        self.instdb = InstrumentDB(self.scandb)

        self.writer = MessageWrite(scandb=scandb)

        self.fileroot = self.scandb.get_info('server_fileroot')
        self.macro_dir = self.scandb.get_info('macro_folder')
        self.loaded_modules = {}


        # take all symbols from macros_init, add, _scandb, _instdb,
        # and add some scanning primitives
        syms = {name: getattr(macros_init, name) for name in macro_syms}

        syms['_scandb'] = self.scandb
        syms['_instdb'] = self.instdb

        readonly = [s for s in syms]

        self.eval = Interpreter(user_symbols=syms,
                                readonly_syms=readonly,
                                builtins_readonly=True,
                                writer=self.writer,
                                err_writer=self.writer,
                                with_import=True,
                                with_importfrom=True)

        self.eval(scan_primitives)
        self.eval.readonly_syms.extend(['get_dbinfo', 'set_dbinfo',
                    'check_scan_abort', 'scan_from_db', 'do_scan',
                    'move_instrument', 'move_samplestage'])

        self.load_macros()



    def check_abort_pause(self, msg='at caget'):
        if self.scandb.test_abort(msg):
            return False
        self.scandb.wait_for_pause(timeout=86400.0)
        return True


    def load_macros(self, macro_dir=None, verbose=False):
        """read latest macros"""
        if macro_dir is None:
            macro_dir = self.macro_dir

        macro_root = self.fileroot
        if os.name == 'nt':
            macro_root = self.scandb.get_info('windows_fileroot')
            if not macro_root.endswith('/'):
                macro_root += '/'

        modpath = Path(macro_root, macro_dir, 'macros').absolute()
        modpathname = modpath.as_posix()
        if not modpath.exists():
            self.scandb.set_info('scan_message',
                                 f"Cannot locate modules in '{modpathname}'")
            print(f"no macros imported from {modpathname}")
            return


        try:
            origdir = os.getcwd()
            os.chdir(modulepathname)
            for name in glob.glob('*.lar'):
                time.sleep(0.025)
                modname = name[:-4]
                # print(" IMPORT MACRO ", name)
                this_mtime = os.stat(name).st_mtime
                if modname in self.loaded_modules:
                    last_mtime = self.loaded_modules[modname]
                    if this_mtime < last_mtime:
                        continue

                self.eval.error = []
                if verbose:
                    print( 'importing module: ', modname)
                if modname in self.loaded_modules:
                    self.eval.run('reload(%s)' % modname)
                else:
                    self.eval.run('import %s' % modname)
                if len(self.eval.error) > 0:
                    emsg = '\n'.join(self.eval.error[0].get_error())
                    self.scandb.set_info('error_message', emsg)
                    print( '==Import Error %s/%s' % (modname, emsg))
                else:
                    if modname not in _sys.searchGroups:
                        _sys.searchGroups.append(modname)
                    self.loaded_modules[modname] = this_mtime
                    thismod  = self.symtab.get_symbol(modname)
                    _sys.searchGroupObjects.append(thismod)
            os.chdir(origdir)
        except OSError:
            print("error loading macros")
        self.scandb.set_path()
        return self.get_macros()

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

        These are taken from the _epics, _scan, and macros groups

        returned dictionary has function names as keys, and docstrings as values
        """
        macros = {}
        symtab = self.symtab
        modlist = [symtab, symtab._epics, symtab._scan]
        for mod in self.loaded_modules:
            if hasattr(symtab, mod):
                modlist.append(getattr(symtab, mod))
        for group in modlist:
            for name in dir(group):
                obj = getattr(group, name)
                if callable(obj) and not name.startswith('_'):
                    doc = getattr(obj, '__doc__', None)
                    if doc is None:
                        doc = ''
                    sig = getattr(obj, '_signature', None)
                    if callable(sig):
                        sig = sig()
                    if 'PRIVATE' not in doc and sig is not None:
                        macros[name] = sig, doc, obj

        return macros
