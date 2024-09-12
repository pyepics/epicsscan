import sys
import socket
import time
import json
from datetime import timedelta

class ScanDBException(Exception):
    """Scan Exception: General Errors"""
    def __init__(self, *args):
        Exception.__init__(self, *args)
        sys.excepthook(*sys.exc_info())

class ScanDBAbort(Exception):
    """Scan Abort Exception"""
    def __init__(self, *args):
        Exception.__init__(self, *args)
        sys.excepthook(*sys.exc_info())

def tstamp():
    return time.strftime("%Y-%b-%d %H:%M:%S")

def hms(secs):
    "format time in seconds to H:M:S"
    return str(timedelta(seconds=int(secs)))

def strip_quotes(t):
    d3, s3, d1, s1 = '"""', "'''", '"', "'"
    if hasattr(t, 'startswith'):
        if ((t.startswith(d3) and t.endswith(d3)) or
            (t.startswith(s3) and t.endswith(s3))):
            t = t[3:-3]
        elif ((t.startswith(d1) and t.endswith(d1)) or
              (t.startswith(s1) and t.endswith(s1))):
            t = t[1:-1]
    return t

def plain_ascii(s, replace=''):
    """
    replace non-ASCII characters with blank or other string
    very restrictive (basically ord(c) < 128 only)
    """
    if s is None: s = ''
    return "".join([i for i in s if ord(i)<128])

def get_units(pv, default):
    try:
        units = pv.units
    except:
        units = ''
    if units in (None, ''):
        units = default
    return units


def normalize_pvname(name):
    """ make sure Epics PV name either ends with .VAL or .SOMETHING!"""
    return name if  '.' in name else f"{name}.VAL"

def json2ascii(inp):
    """convert input unicode json text to pure ASCII/utf-8"""
    if isinstance(inp, dict):
        return dict([(json2ascii(k), json2ascii(v)) for k, v in inp.iteritems()])
    elif isinstance(inp, list):
        return [json2ascii(k) for k in inp]
    elif isinstance(inp, unicode):
        return inp.encode('utf-8')
    else:
        return inp


PARENS = {'{': '}', '(': ')', '[': ']'}
OPENS  = ''.join(PARENS.keys())
CLOSES = ''.join(PARENS.values())
QUOTES = '\'"'
BSLASH = '\\'
COMMENT = '#'
DBSLASH = '\\\\'

def find_eostring(txt, eos, istart):
    """find end of string token for a string"""
    while True:
        inext = txt[istart:].find(eos)
        if inext < 0:  # reached end of text before match found
            return eos, len(txt)
        elif (txt[istart+inext-1] == BSLASH and
              txt[istart+inext-2] != BSLASH):  # matched quote was escaped
            istart = istart+inext+len(eos)
        else: # real match found! skip ahead in string
            return '', istart+inext+len(eos)-1


def is_complete(text):
    """
    returns whether a text of code is complete
    for strings quotes and open / close delimiters,
    including nested delimeters.
    """
    itok, istart, eos = 0, 0, ''
    delims = []
    while itok < len(text):
        c = text[itok]
        if c in QUOTES:
            eos = c
            if text[itok:itok+3] == c*3:
                eos = c*3
            istart = itok + len(eos)
            # leap ahead to matching quote, ignoring text within
            eos, itok = find_eostring(text, eos, istart)
        elif c in OPENS:
            delims.append(PARENS[c])
        elif c in CLOSES and len(delims) > 0 and c == delims[-1]:
            delims.pop()
        elif c == COMMENT and eos == '': # comment char outside string
            jtok = itok
            if '\n' in text[itok:]:
                itok = itok + text[itok:].index('\n')
            else:
                itok = len(text)
        itok += 1
    return eos=='' and len(delims)==0 and not text.rstrip().endswith(BSLASH)
