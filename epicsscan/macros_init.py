#!/usr/bin/env python
"""
Macro symbols and builtin function for EpicsScan MacroKernel

"""

import numpy as np
import scipy.constants as consts

from epics import caget, caput, get_pv, PV
from time import monotonic as clock, sleep
from xraydb import (atomic_density, atomic_mass, atomic_name, atomic_number,
          atomic_symbol, chemparse, core_width, darwin_width, f0, f1_chantler,
          f2_chantler, fluor_yield, get_material, guess_edge,
          ionchamber_fluxes, ionization_potential, material_mu,
          material_mu_components, mirror_reflectivity, mu_chantler, mu_elam,
          xray_delta_beta, xray_edge, xray_edges, xray_line, xray_lines)

INITSYMS = ['clock', 'sleep', 'caget', 'caput', 'get_pv', 'PV', 'consts',
            'etok', 'ktoe', 'AMU', 'ATOM_NAMES', 'ATOM_SYMS', 'AVOGADRO',
            'DEG2RAD', 'E_MASS', 'PI', 'PLANCK_HBARC', 'PLANCK_HC', 'RAD2DEG',
            'RYDBERG', 'R_ELECTRON_ANG', 'R_ELECTRON_CM', 'SI_PREFIXES',
            'TAU', 'XAFS_KTOE', 'atomic_density', 'atomic_mass',
            'atomic_name', 'atomic_number', 'atomic_symbol', 'chemparse',
            'core_width', 'darwin_width', 'f0', 'f1_chantler', 'f2_chantler',
            'fluor_yield', 'get_material', 'guess_edge', 'index_nearest',
            'index_of', 'ionchamber_fluxes', 'ionization_potential',
            'material_mu', 'material_mu_components', 'mirror_reflectivity',
            'mu_elam', 'xray_delta_beta', 'xray_edge', 'xray_edges',
            'xray_line', 'xray_lines', 'get_dbinfo', 'set_dbinfo',
            'check_scan_abort', 'scan_from_db', 'do_scan', 'do_slewscan',
            'move_instrument', 'move_samplestage']

physical_constants = consts.physical_constants

PI = np.pi
TAU = 2*np.pi

DEG2RAD = TAU/360
RAD2DEG = 1.0/DEG2RAD

# atoms/mol =  6.0221413e23  atoms/mol
AVOGADRO = consts.Avogadro

# ATOMIC MASS in grams
AMU = consts.atomic_mass * 1000.0

# electron rest mass in eV
E_MASS = consts.electron_mass * consts.c**2 / consts.e

# Planck's Constant
#   h*c    ~= 12398.42 eV*Ang
#   hbar*c ~=  1973.27 eV*Ang
PLANCK_HC    = 1.e10 * consts.Planck * consts.c / consts.e
PLANCK_HBARC = PLANCK_HC / TAU

# Rydberg constant in eV (~13.6 eV)
RYDBERG = consts.Rydberg * consts.Planck * consts.c/ consts.e

# classical electron radius in cm and Ang
R_ELECTRON_CM  = 100.0 * consts.physical_constants['classical electron radius'][0]
R_ELECTRON_ANG = 1.e8 * R_ELECTRON_CM

# XAFS K to E # 3.8099819442818976
XAFS_KTOE = 1.e20*consts.hbar**2 / (2*consts.m_e * consts.e)

# will be able to import these from xraydb when v 4.5.1 is required
ATOM_SYMS = ['H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg',
           'Al', 'Si', 'P', 'S', 'Cl', 'Ar', 'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr',
           'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br',
           'Kr', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd',
           'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe', 'Cs', 'Ba', 'La',
           'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er',
           'Tm', 'Yb', 'Lu', 'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au',
           'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn', 'Fr', 'Ra', 'Ac', 'Th',
           'Pa', 'U', 'Np', 'Pu', 'Am', 'Cm', 'Bk', 'Cf', 'Es', 'Fm', 'Md',
           'No', 'Lr', 'Rf', 'Db', 'Sg', 'Bh', 'Hs', 'Mt', 'Ds', 'Rg', 'Cn',
           'Nh', 'Fl', 'Mc', 'Lv', 'Ts', 'Og']

ATOM_NAMES = ['hydrogen', 'helium', 'lithium', 'beryllium', 'boron', 'carbon',
            'nitrogen', 'oxygen', 'fluorine', 'neon', 'sodium', 'magnesium',
            'aluminum', 'silicon', 'phosphorus', 'sulfur', 'chlorine', 'argon',
            'potassium', 'calcium', 'scandium', 'titanium', 'vanadium',
            'chromium', 'manganese', 'iron', 'cobalt', 'nickel', 'copper',
            'zinc', 'gallium', 'germanium', 'arsenic', 'selenium', 'bromine',
            'krypton', 'rubidium', 'strontium', 'yttrium', 'zirconium',
            'niobium', 'molybdenum', 'technetium', 'ruthenium', 'rhodium',
            'palladium', 'silver', 'cadmium', 'indium', 'tin', 'antimony',
            'tellurium', 'iodine', 'xenon', 'cesium', 'barium', 'lanthanum',
            'cerium', 'praseodymium', 'neodymium', 'promethium', 'samarium',
            'europium', 'gadolinium', 'terbium', 'dysprosium', 'holmium',
            'erbium', 'thulium', 'ytterbium', 'lutetium', 'hafnium',
            'tantalum', 'tungsten', 'rhenium', 'osmium', 'iridium', 'platinum',
            'gold', 'mercury', 'thallium', 'lead', 'bismuth', 'polonium',
            'astatine', 'radon', 'francium', 'radium', 'actinium', 'thorium',
            'protactinium', 'uranium', 'neptunium', 'plutonium', 'americium',
            'curium', 'berkelium', 'californium', 'einsteinium', 'fermium',
            'mendelevium', 'nobelium', 'lawrencium', 'rutherfordium',
            'dubnium', 'seaborgium', 'bohrium', 'hassium', 'meitnerium',
            'darmstadtium', 'roentgenium', 'copernicium', 'nihonium',
            'flerovium', 'moscovium', 'livermorium', 'tennessine', 'oganesson']


SI_PREFIXES = {'y': 1.e-24, 'yocto': 1.e-24,
               'z': 1.e-21, 'zepto': 1.e-21,
               'a': 1.e-18, 'atto': 1.e-18,
               'f': 1.e-15, 'femto': 1.e-15,
               'p': 1.e-12, 'pico': 1.e-12,
               'n': 1.e-9, 'nano': 1.e-9,
               '\u03bc': 1.e-6, 'u': 1.e-6, 'micro': 1.e-6,
               'm': 1.e-3, 'milli': 1.e-3,
               'c': 1.e-2, 'centi': 1.e-2,
               'd': 1.e-1, 'deci': 1.e-1,
               'da': 1.e1, 'deka': 1.e1,
               'h': 1.e2, 'hecto': 1.e2,
               'k': 1.e3, 'kilo': 1.e3,
               'M': 1.e6, 'mega': 1.e6,
               'G': 1.e9, 'giga': 1.e9,
               'T': 1.e12, 'tera': 1.e12,
               'P': 1.e15, 'peta': 1.e15,
               'E': 1.e18, 'exa': 1.e18,
               'Z': 1.e21, 'zetta': 1.e21,
               'Y': 1.e24, 'yotta': 1.e24,
  }


def etok(energy):
    """convert photo-electron energy to wavenumber"""
    if energy < 0: return 0
    return np.sqrt(energy/XAFS_KTOE)

def ktoe(k):
    """convert photo-electron wavenumber to energy"""
    if k < 0: return 0
    return XAFS_KTOE*k*k

def as_ndarray(obj):
    """
    make sure a float, int, list of floats or ints,
    or tuple of floats or ints, acts as a numpy array
    """
    if isinstance(obj, (float, int)):
        return np.array([obj])
    return np.asarray(obj)

def index_of(array, value):
    """
    return index of array *at or below* value
    returns 0 if value < min(array)

    >> ix = index_of(array, value)

    Arguments
    ---------
    array  (ndarray-like):  array to find index in
    value  (float): value to find index of

    Returns
    -------
    integer for index in array at or below value
    """
    if value < min(array):
        return 0
    return max(np.where(array<=value)[0])

def index_nearest(array, value):
    """
    return index of array *nearest* to value

    >>> ix = index_nearest(array, value)

    Arguments
    ---------
    array  (ndarray-like):  array to find index in
    value  (float): value to find index of

    Returns
    -------
    integer for index in array nearest value

    """
    return np.abs(array-value).argmin()


def scan_from_db(scanname, filename="scan.001"):
    """
    get scan definition from ScanDB by name
    """
    try:
        scan = _scandb.make_scan(scanname)
        scan.filename = filename
        scan.mkernel = _mkernel
    except:
        raise ValueError(f"no scan definition '{scanname}' found")
    return scan

def do_scan(scanname, filename="scan.001", nscans=1, comments=""):
    """do_scan(scanname, filename="scan.001", nscans=1, comments="")

    execute a step scan as defined in Scan database

    Arguments
    ---------
    scanname (string): name of scan
    filename (string): name of output data file ['scan.001']
    comments (string): user comments for file ['']
    nscans (integer):  number of repeats to make. [1]

    Examples
    --------
      do_scan("cu_xafs", "cu_sample1.001", nscans=3)

    Notes
    -----
      1. The filename will be incremented so that each scan uses a new filename.
    """
    if nscans is not None:
        _scandb.set_info("nscans", nscans)

    scan = scan_from_db(scanname, filename=filename)
    scan.comments = comments
    if scan.scantype == "slew":
        return scan.run(filename=filename, comments=comments)
    else:
        nscans_done = 0
        nscans_left = get_dbinfo("nscans", as_int=True)
        if get_dbinfo("request_abort", as_bool=True):
            nscans_left = -1
        while nscans_left > 0:
            scan.run()
            nscans_done += 1
            nscans_left = get_dbinfo("nscans", as_int=True) - nscans_done
            if get_dbinfo("request_abort", as_bool=True):
                nscans_left = -1
        return scan

def do_slewscan(scanname, filename="scan.001", nscans=1, comments=""):
    """do_scan(scanname, filename="scan.001", nscans=1, comments="")

    execute a slew scan as defined in Scan database

    Arguments
    ---------
    scanname (string):  name of scan
    filename (string):  name of output data file ['scan.001']
    comments (string): user comments for file ['']
    nscans (integr):   number of repeats to make. [1]

    Examples
    --------
      do_slewscan("cu_xafs", "cu_sample1.001", nscans=3)

    Notes
    -----
      1. The filename will be incremented so that each scan uses a new filename.
    """
    if nscans is not None:
        _scandb.set_info("nscans", nscans)

    scan = scan_from_db(scanname, filename=filename)
    scan.comments = comments
    if scan.scantype != "slew":
        return do_scan(scanname, filename=filename, nscans=nscans, comments=comments)
    else:
        return scan.run(filename=filename, comments=comments)

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

def check_scan_abort():
    """returns whether Abort has been requested"""
    return get_dbinfo('request_abort', as_bool=True)

def move_instrument(inst_name, position_name, wait=True, infoname=None, timeout=60.0):
    """move an Epics Instrument to a named position

    Arguments
    ---------
    inst_name (string):     name of Epics Instrument
    position_name (string): name of position for the Instrument
    wait (True or False):   whether to wait for move to complete [True]
    timeout (float):        time in seconds to give up waiting [60]

    Examples
    -------
       move_instrument('Double H Mirror Stripes', 'platinum', wait=True)

    """
    _instdb.restore_position(inst_name, position_name, wait=wait, timeout=timeout)
    if infoname is not None:
        _scandb.set_info(infoname, position_name)


def move_samplestage(position_name, wait=True, timeout=60.0):
    """move Instrument for Samplestage to a named position

    Arguments
    ---------
    position_name (string): name of sample position
    wait (True or False):   whether to wait for move to complete [True]
    timeout (float):        time in seconds to give up waiting [60]

    Notes
    -----
     the instrument for the sample will be fetched from
             _scandb.get_info('samplestage_instrument')

    Examples
    --------
        move_sample('Map1 positionA', wait=True)

    """
    inst_name = _scandb.get_info('samplestage_instrument')
    eprefix = _scandb.get_info('epics_status_prefix', None)
    if eprefix is not None:
        pospv_name = get_pv(f'{eprefix}PositionName')
        pospv_name.put(position_name)
    _scandb.set_info('sample_position', position_name)
    _instdb.restore_position(inst_name, position_name, wait=wait, timeout=timeout)
