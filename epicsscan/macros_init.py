import numpy as np
import scipy.constants as consts

from epics import caget, caput, get_pv, PV

from xraydb import (atomic_density, atomic_mass, atomic_name, atomic_number,
          atomic_symbol, chemparse, core_width, darwin_width, f0, f1_chantler,
          f2_chantler, fluor_yield, get_material, guess_edge,
          ionchamber_fluxes, ionization_potential, material_mu,
          material_mu_components, mirror_reflectivity, mu_chantler, mu_elam,
          xray_delta_beta, xray_edge, xray_edges, xray_line, xray_lines)


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

#
XAFS_KTOE = 1.e20*consts.hbar**2 / (2*consts.m_e * consts.e) # 3.8099819442818976

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
