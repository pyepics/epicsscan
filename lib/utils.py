
import socket

def atGSECARS():
    ipaddr = socket.gethostbyname(socket.gethostname())
    return ipaddr.startswith('164.54.160')

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
    return "".join(i for i in s if ord(i)<128)

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
    if  '.' in name:
        return name
    return "%s.VAL" % name

def pv_fullname(name):
    """ make sure Epics PV name either ends with .VAL or .SOMETHING!"""
    if  '.' in name:
        return name
    return "%s.VAL" % name

def asciikeys(adict):
    """ensure a dictionary has ASCII keys (and so can be an **kwargs)"""
    return dict((k.encode('ascii'), v) for k, v in adict.items())


def read_oldscanfile(fname):
    out = {'type': 'linear'}
    with open(fname, 'r') as fh:
        lines = fh.readlines()
    if len(lines) < 1:
        return out
    sect = 'head'
    nreg = 1
    isrel = False
    iskspace = [False]*5
    dtimes = [1]*5
    starts = [0]*5
    stops  = [0]*5
    steps  = [0]*5
    pos = -1
    for line in lines:
        line  = line[:-1].strip()
        key, val =  line, ''
        if '%' in line:
            key, val = [s.strip() for s in line.split('%')]
        if key.startswith(';scan'):
            if sect == 'head':
                sect = 'scan'
            else:
                break
        if key == 'datafile':
            out['filename'] = val
        elif key == 'type' and val == 'EXAFS':
            out['type'] = 'xafs'
        elif key == 'n_regions':
            nreg = int(val)
        elif key == 'is_rel':
            isrel = ('1' == val)
        elif key == 'delay':
            pdel, ddel = [float(x) for x in val]
            out['pos_settle_time'] = pdel
            out['det_settle_time'] = ddel
        elif key == 'is_kspace':
            iskspace =[(float(x)>0.1) for x in val.split()]
        elif key == 'time':
            dtimes =[float(x) for x in val.split()]
        elif key == 'npts':
            npts   =[int(float(x)) for x in val.split()]
        elif key == 'params':
            dat = [float(x) for x in val.split()]
            out['e0'] = dat[0]
            out['time_kw'] = dat[1]
            out['max_time'] = dat[2]
        elif key == 'pos':
            pos = int(val)
        elif key == 'start' and pos == 0:
            starts = [float(x) for x in val.split()]
        elif key == 'stop' and pos == 0:
            stops = [float(x) for x in val.split()]
        elif key == 'step' and pos == 0:
            steps = [float(x) for x in val.split()]

    #
    regions = []
    out['dwelltime'] = dtimes[0]
    for i in range(nreg):
        start= starts[i]
        stop = stops[i]
        step = steps[i]
        dtime = dtimes[i]
        npt   = npts[i]
        units = 'k' if iskspace[i] else 'eV'
        regions.append((start, stop, npt, dtime, units))

    out['is_relative'] = isrel
    out['regions'] = regions
    return out
