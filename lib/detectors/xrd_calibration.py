import time

def read_poni(fname):
    """read pyFAI poni file to dict
    """
    conf = {}
    with open(fname, 'r') as fh:
        for line in fh.readlines():
            line = line[:-1].strip()
            if line.startswith('#'):
                continue
            key, val = [a.strip() for a in line.split(':')]
            key = key.lower()
            if key == 'distance': key='dist'
            if key == 'pixelsize1': key='pixel1'
            if key == 'pixelsize2': key='pixel2'
            conf[key] = float(val)
    return conf

def write_poni(filename, calname='', pixel1=0, pixel2=0,
               poni1=0, poni2=0, dist=0, rot1=0, rot2=0, rot3=0,
               wavelength=0, **kws):
    buff = '''# XRD Calibration  {calname:s}
# Saved {ctime:s}
PixelSize1: {pixel1:16.11g}
PixelSize2: {pixel2:16.11g}
Distance: {dist:16.11g}
Poni1: {poni1:16.11g}
Poni2: {poni2:16.11g}
Rot1: {rot1:16.11g}
Rot2: {rot2:16.11g}
Rot3: {rot3:16.11g}
Wavelength: {wavelength:16.11g}
'''
    with open(filename, 'w') as fh:
        fh.write(buff.format(calname=calname, ctime=time.ctime(),
                             pixel1=pixel1, pixel2=pixel2,
                             poni1=poni1, poni2=poni2,
                             rot1=rot1, rot2=rot2, rot3=rot3,
                             dist=dist, wavelength=wavelength))
