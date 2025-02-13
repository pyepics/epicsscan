#!/usr/bin/python
"""
file utilities
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from random import randint

def bytes2str(s):
    'bytes2str'
    if isinstance(s, str):
        return s
    if isinstance(s, bytes):
        return s.decode(sys.stdout.encoding)
    return str(s, sys.stdout.encoding)

def str2bytes(s):
    'string to byte conversion'
    if isinstance(s, bytes):
        return s
    return bytes(s, sys.stdout.encoding)


BAD_FILECHARS = ';~,`!%$@?*#:"/|\'\\\t\r\n (){}[]<>'
BAD_FILETABLE = str.maketrans(BAD_FILECHARS, '_'*len(BAD_FILECHARS))

def get_timestamp():
    """return ISO format of current timestamp:
    2012-04-27 17:31:12
    """
    return datetime.isoformat(datetime.now(), sep=' ', timespec='seconds')


def fix_varname(s):
    """fix string to be a 'good' variable name."""
    t = str(s).translate(BAD_FILETABLE)
    t = t.replace('.', '_').replace('-', '_')
    while t.endswith('_'):
        t = t[:-1]
    return t

def fix_filename(s):
    """fix string to be a 'good' filename.
    This may be a more restrictive than the OS, but
    avoids nasty cases."""
    t = str(s).translate(BAD_FILETABLE)
    if t.count('.') > 1:
        for _ in range(t.count('.') - 1):
            idot = t.find('.')
            t = f"{t[:idot]}_{t[idot+1:]}"
    return t


def random_string(n):
    """  random_string(n)
    generates a random string of length n, that will match this pattern:
       [a-z](n)
    """
    return ''.join([chr(randint(97, 122)) for i in range(n)])

def pathof(dirname, base, ext, delim='.', absolute=False):
    "path combine"
    fpath = Path(dirname, f"{base}{delim}{ext}")
    if absolute:
        fpath = fpath.absolute()
    return fpath.as_posix()

def increment_filename(inpfile, ndigits=3, delim='.', absolute=False):
    """
    increment a data filename, returning a new (non-existing) filename

       first see if a number is after '.'.  if so, increment it.
       second look for number in the prefix. if so, increment it.
       lastly, insert a '_001' before the '.', preserving suffix.

    the numerical part of the file name will contain at least three digits.

    >>> increment_filename('a.002')
    'a.003'
    >>> increment_filename('a.999')
    'a.1000'
    >>> increment_filename('b_017.xrf')
    'b_018.xrf'
    >>> increment_filename('x_10300243.dat')
    'x_10300244.dat'

    >>> increment_filename('x.dat')
    'x_001.dat'

    >>> increment_filename('C:/program files/oo/data/x.002')
    'C:/program files/ifeffit/data/x.003'

    >>> increment_filename('a_001.dat')
    'a_002.dat'
    >>> increment_filename('a_6.dat')
    'a_007.dat'

    >>> increment_filename('a_001.002')
    'a_001.003'

    >>> increment_filename('a')
    'a.001'

    >>> increment_filename("path/a.003")
    'path/a.004'
"""

    dirname,  filename = os.path.split(inpfile)
    base, ext = os.path.splitext(filename)
    base, ext = '', ''
    base = filename.split(delim, 1)
    if len(base) == 2:
        base, ext = base
    elif len(base) == 1:
        base, ext = base[0], '.000'

    if ext.startswith('.'):
        ext   = ext[1:]
    ndig = max(3, ndigits)

    def _incr(base, ext):
        try: # first, try incrementing the file extension
            ext = f"{(int(ext)+1):0{ndig}d}"
        except ValueError:
            try: #  try incrementing the part of the base after the last '_'
                bparts = base.split('_')
                bparts[-1] = f"{(int(bparts[-1])+1):0{ndig}d}"
                base = '_'.join(bparts)
            except ValueError:  # last, add a '_001' appendix
                base = f"{base}_001"
        return (base, ext)

    # increment once

    base, ext = _incr(base, ext)
    fout      = pathof(dirname, base, ext, delim=delim, absolute=absolute)

    # then gaurantee that file does not exist,
    # continuing to increment if necessary
    while os.path.exists(fout):
        base,ext = _incr(base, ext)
        fout     = pathof(dirname, base, ext, delim=delim, absolute=absolute)
    return fout

def new_filename(fname=None, ndigits=3):
    """ generate a new file name, either based on
    filename or generating a random one

    >>> new_filename(fname='x.001')
    'x.002'
    # if 'x.001' exists
    """
    ndig = max(3, ndigits)
    if fname is None:
        fname = f"{random_string(6)}.{(1):0{ndig}d}"

    if os.path.exists(fname):
        fname = increment_filename(fname, ndigits=ndig)

    return fname

def new_dirname(dirname=None, ndigits=3):
    """ generate a new subdirectory name (no '.' in name), either
    based on dirname or generating a random one

    >>> new_dirname('x.001')
    'x_002'
    # if 'x_001' exists
    """
    ndig = max(3, ndigits)
    if dirname is None:
        dirname = f"{random_string(6)}.{(1):0{ndig}d}"

    dirname = dirname.replace('.', '_')
    if os.path.exists(dirname):
        dirname = increment_filename(dirname, ndigits=ndig, delim='_')
    return dirname

def test_inc():
    "test"
    test = ( ('a.002', 'a.003'),
             ('a.999', 'a.1000'),
             ('b_017.xrf',  'b_018.xrf'),
             ('x_10300243.dat', 'x_10300244.dat'),
             ('x.dat' , 'x_001.dat'),
             ('C:/program files/data/x.002',
              'C:/program files/data/x.003'),
             ('a_001.dat', 'a_002.dat'),
             ('a_6.dat', 'a_007.dat'),
             ('a_001.002', 'a_001.003'),
             ('path/a.003',  'path/a.004'))
    npass = nfail = 0
    for inp, out in test:
        tval = increment_filename(inp, absolute=False)
        if tval != out:
            print("Error converting " , inp)
            print(f"Got '{tval}'  expected '{out}'")
            nfail = nfail + 1
        else:
            npass = npass + 1
    print(f"Passed {npass} of {npass+nfail} tests")

if __name__ == '__main__':
    test_inc()
