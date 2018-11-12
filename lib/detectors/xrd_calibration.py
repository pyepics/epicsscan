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
PixelSize1: {pixel1:14.7g}
PixelSize2: {pixel2:14.7g}
Distance: {dist:14.7g}
Poni1: {poni1:14.7g}
Poni2: {poni2:14.7g}
Rot1: {rot1:14.7g}
Rot2: {rot2:14.7g}
Rot3: {rot3:14.7g}
Wavelength: {wavelength:14.7g}
'''
    with open(filename, 'w') as fh:
        fh.write(buff.format(calname=calname, ctime=time.ctime(),
                             pixel1=pixel1, pixel2=pixel2,
                             poni1=poni1, poni2=poni2,
                             rot1=rot1, rot2=rot2, rot3=rot3,
                             dist=dist, wavelength=wavelength))
