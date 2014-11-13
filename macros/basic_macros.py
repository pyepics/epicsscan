#!/usr/bin/env python
"""
basic larch scanning macros
"""

import os
from ConfigParser import ConfigParser

from time import sleep, clock
from numpy import linspace
from epics import caput, caget
from larch import Group
from larch.utils import OrderedDict

DEF_SampleStageFile = 'SampleStage_autosave.ini'

def read_stageconfig(filename=None, _larch=None):
    """read Sample Stage configurattion file, saving results

    Parameters
    ----------
    filename:   None or string, name of file holding sample positions (see Note)

    Examples
    --------
      read_stageconfig()

    Notes
    ------
      1. If filename is None (the default) 'SampleStage_autosave.ini'
         from the current working folder is used.
      2. the file timestamp is always tested to find new position names
      3. Generally, you don't need to do this explicitly, as
         move_samplestage will run this when necessary.

    """
    if filename is None: filename = DEF_SampleStageFile
    if not os.path.exists(filename): 
       print 'No stageconfig found!'
       return None
    #endif

    stages = []
    positions = OrderedDict()
    ini = ConfigParser()
    ini.read(filename)

    for item in ini.options('stages'):
        line = ini.get('stages', item)
        words = [i.strip() for i in line.split('||')]
        stages.append(words[0])
    #endfor

    for item in ini.options('positions'):
        line = ini.get('positions', item)
        words = [i.strip() for i in line.split('||')]
        name = words[0].lower()
        vals = [float(i) for i in words[2].split(',')]
        positions[name] = vals
    #endfor
    this = Group(pos=positions, stages=stages,
                 _modtime_=os.stat(filename).st_mtime)
    if _larch is not None:
        if not _larch.symtable.has_group('macros'):
            _larch.symtable.new_group('macros')
        _larch.symtable.macros.stage_conf = this
    print(" Read %d positions from stage configuration." % len(positions) )
        
    return this
#enddef

def move_samplestage(position, filename=None, wait=True, _larch=None):
    """move Sample Stage to named position

    Parameters
    ----------
    position:  string, named stage position
    filename:  None or string, name of file holding sample positions (see Note)
    wait:     True/False, whether to wait for move to complete (default True)

    Examples
    --------
      move_samplestage('Sample 1')

    Notes
    ------
      1. If filename is None (the default) 'SampleStage_autosave.ini' 
         from the current working folder is used.
      2. the file timestamp is always tested to find new position names

    """
    _conf = None
    if _larch is not None:
        _conf = getattr(_larch.symtable.macros, 'stage_conf', None)
    if _conf is not None:
        # check if the stage config file has changed since last reading
        if filename is None: filename = DEF_SampleStageFile
        if os.stat(filename).st_mtime > _conf._modtime_:
            _conf = None
    #endif
    if _conf is None:
        _conf = read_stageconfig(filename=filename)
    #endif

    if _conf is None:
        print(" cannot read stage config '%s;" % filename)
        return None
    #endif

    posname = position.lower()
    if posname not in _conf.pos:
        print(" cannot find position named '%s;" % position)
        return None
    #endif

    # get values for this position, caput without waiting
    vals = _conf.pos[posname]
    for pvname, value in zip(_conf.stages, vals):
        caput(pvname, value, wait=False)
    #endfor

    if wait:
        for pvname, value in zip(_conf.stages, vals):
            caput(pvname, value, wait=True)
        #endfor
    #endif
#enddef


def test_samplestage(position, filename=None, wait=True, _larch=None):
    """PRIVATE
    tests moving to a samplestage position

    Parameters
    ----------
    val:      number, nominal stage position
    pvname:   string, name of detector distance PV ('13IDE:m19.VAL')
    wait:     True/False, whether to wait for move to complete (True)

    Examples
    --------
      detector_distance(30)
      
    """

    _conf = None
    if _larch is not None:
        _conf = getattr(_larch.symtable.macros, 'stage_conf', None)
    if _conf is not None:
        # check if the stage config file has changed since last reading
        if filename is None: filename = DEF_SampleStageFile
        if os.stat(filename).st_mtime > _conf.mtime: _conf = None
    #endif
    if _conf is None:
        _conf = read_stageconfig(filename=filename)
    #endif

    if _conf is None:
        print(" cannot read stage config '%s;" % filename)
        return None
    #endif

    posname = position.lower()
    if posname not in _conf.pos:
        print(" cannot find position named '%s;" % position)
        return None
    #endif

    # get values for this position, caput without waiting
    vals = _conf.pos[posname]
    for pvname, value in zip(_conf.stages, vals):
        print(" -- Would put %s to %s" % (pvname, repr(value)))
    #endfor
#enddef


def detector_distance(val, pvname='13IDE:m19.VAL', wait=True):
    """move detector distance to stage position value

    Parameters
    ----------
    val:      number, nominal stage position
    pvname:   string, name of detector distance PV ('13IDE:m19.VAL')
    wait:     True/False, whether to wait for move to complete (True)

    Examples
    --------
      detector_distance(30)
      
    """
    return caput(pvname, val, wait=wait)

def move_instrument(inst_name, position_name, wait=False,
                    prefix='13XRM:Inst:', timeout=60.0):
    """move an Epics Instrument to a named position

    Parameters
    ----------
    inst_name:      string, name of Epics Instrument
    position_name:  string, name of position for the Instrument
    wait:           True/False, whether to wait for move to complete (False)
    prefix:         string PV prefix used by Epics Instrument ('13XRM:Inst:')
    timeout:        time in seconds to give up waiting

    Examples
    --------
      move_instrument('Double H Mirror Stripes', 'platinum', wait=True)

    Notes
    ------
    This requires a working Epics Instrument program to be running.
    
    """

    'move an Epics Instrument to a named position'
    caput(prefix + 'InstName', inst_name)
    caput(prefix + 'PosName', position_name)
    sleep(0.25)
    if (caget(prefix + 'InstOK') == 1 and
        caget(prefix + 'PosOK') == 1):
        caput(prefix + 'Move', 1)
        if wait:
            moving, t0 = 1, clock()
            while moving:
                sleep(0.25)
                moving = ((1 == caget(prefix + 'Move')) or
                          (clock()-t0 > timeout))
            #endwhile
        #endif
    #endif
#enddef

def move_energy(energy, id_offset=None, id_harmonic=None):
    """move energy to desired value

    Parameters
    ----------
    energy:       energy in eV
    id_offset:    None or  undulator - energy offset (in keV!)
                  if None (default) the value will not be changed
    id_harmonic:  None or undulator harmonic
                  if None (default) the value will not be changed    

    Examples
    --------
      move_energy(5000,  id_offset=0.050, id_harmonic=1)
      move_energy(12000, id_offset=0.120, id_harmonic=3)
    """
    if id_harmonic is not None:
        caput('13IDE:En:id_harmonic.VAL', id_harmonic)
    #endif

    if id_offset is not None:
        caput('13IDE:En:id_off.VAL', id_offset)
    #endif

    caput('13IDE:En:y2_track', 1)
    caput('13IDE:En:id_track', 1)
    caput('13IDE:En:id_wait',  0)
    caput('13IDE:En:Energy.VAL', energy, wait=True)
    sleep(1.0)
#enddef

def set_SRSgain(sens, unit, prefix='13IDE:A1', offset=100):
    """set pre-amplifier sensitivity, units, and offset

    Parameters
    ----------
    sens:   number for sensitivity
            one of (1, 2, 5, 10, 20, 50, 100, 200, 500)
    units:  string for units
            one of  ('pA/V', 'nA/V', 'uA/V', 'mA/V')
    prefix: string for SRS Amplifier PV prefix [default '13IIDE:A1']
    offset: number for current offset  [default 100]

    Examples
    --------
    set_SRSamp_gain(100, 'nA/V', prefix='13IDE:A2', offset=105)
    """
    steps = [1, 2, 5, 10, 20, 50, 100, 200, 500]
    units = ['pa/v', 'na/v','ua/v', 'ma/v']

    sens_val = steps.index(sens)
    unit_val = units.index(unit.lower())

    caput("%ssens_unit.VAL" % prefix, unit_val)
    caput("%ssens_num.VAL"  % prefix, sens_val)
    if sens_val > 2:
        sens_val -= 3
    else:
        sens_val += 6
        unit_val -= 1
    #endif
    caput("%soffset_unit.VAL" % prefix, unit_val)
    caput("%soffset_num.VAL"  % prefix, sens_val)
    caput("%soff_u_put.VAL"   % prefix, offset)
#enddef

def set_i1amp_gain(sens, unit, offset=100):
    """set I1 pre-amplifier sensitivity, units, and offset

    Parameters
    ----------
    sens:   number for sensitivity
            one of (1, 2, 5, 10, 20, 50, 100, 200, 500)
    units:  string for units
            one of  ('pA/V', 'nA/V', 'uA/V', 'mA/V')
    offset: number for current offset  [default 100]

    Examples
    --------
    set_i1amp_gain(100, 'nA/V')
    """
    set_SRSgain(sens, unit, prefix='13IDE:A2', offset=offset)
#enddef

def set_i0amp_gain(sens, unit, offset=100):
    """set I0 pre-amplifier sensitivity, units, and offset

    Parameters
    ----------
    sens:   number for sensitivity
            one of (1, 2, 5, 10, 20, 50, 100, 200, 500)
    units:  string for units
            one of  ('pA/V', 'nA/V', 'uA/V', 'mA/V')
    offset: number for current offset  [default 100]

    Examples
    --------
    set_i0amp_gain(100, 'nA/V')
    """
    set_SRSgain(sens, unit, prefix='13IDE:A1', offset=offset)
#enddef


def find_max_intensity(readpv, drivepv, vals, minval=0.1):
    """find a max in an intensity while sweeping through an
    array of drive values,  around a current position, and
    move to the position with max intensity.

    Parameters
    ----------
    readpv:   PV for reading intensity
    drivepv:  PV for driving positions
    vals:     array of RELATIVE positions (from current value)
    minval:   minimum acceptable intensity [defualt = 0.1]

    Notes:
    -------
     1. PRIVATE method, not exposed in user-macros
     2. if the best intensity is below minval, the position is
        moved back to the original position.
     
    """
    _orig = _best = caget(drivepv)
    i0max = caget(readpv)
    for val in _orig+vals:
        caput(drivepv, val)
        sleep(0.1)
        i0 = caget(readpv)
        if i0 > i0max:
            i0max, _best = i0, val
        #endif
    #endfor
    if i0max < minval: _best = _orig
    caput(drivepv, _best)
    return i0max, _best
#enddef

def set_mono_tilt(enable_fb_roll=True, enable_fb_pitch=False):
    """Adjust IDE monochromator 2nd crystal tilt and roll
    to maximize intensity.

    Parameters
    ----------
    enable_fb_roll:  True (default) or False:
                     enable roll feedback after best position is found.
    enable_fb_pitch: True or False (default):
                     enable pitch feedback after best position is found.

    Notes:
    -------
     This works by
        1. adjusting pitch to maximize intensity at BPM
        2. adjusting roll to maximize intensity at I0 Ion Chamber
        3. adjusting pitch to maximize intensity at I0 Ion Chamber
    """

    print 'Set Mono Tilt Oct-2014'
    with_roll = True
    tilt_pv = '13IDA:DAC1_7.VAL'
    roll_pv = '13IDA:DAC1_8.VAL'
    i0_pv   = '13IDE:IP330_1.VAL'
    sum_pv  = '13IDA:QE2:Sum1234:MeanValue_RBV'

    caput('13XRM:edb:use_fb', 0)
    caput('13IDA:efast_pitch_pid.FBON', 0)
    caput('13IDA:efast_roll_pid.FBON', 0)

    i0_minval = 0.1   # expected smallest I0 Voltage

    # stop, restart Quad Electrometer
    caput('13IDA:QE2:Acquire', 0) ;     sleep(0.25)
    caput('13IDA:QE2:Acquire', 1) ;     sleep(0.25)
    caput('13IDA:QE2:ReadData.PROC', 1)

    # find best tilt value with BPM sum
    out = find_max_intensity(sum_pv, tilt_pv, linspace(-2.5, 2.5, 101))
    print 'Best Pitch: %.3f at %.3f ' % (out)
    sleep(0.5)

    # find best roll with I0
    if with_roll:
        print 'doing roll..'
        out = find_max_intensity(i0_pv, roll_pv, linspace(-3.0, 3.0, 61))
        if out[0] > 0.1:
            out = find_max_intensity(i0_pv, roll_pv, linspace(1.0, -1.0, 51))
        #endif
        print 'Best Roll %.3f at %.3f ' % (out)
        sleep(0.5)
    #endif

    # re-find best tilt value, now using I0
    out = find_max_intensity(i0_pv, tilt_pv, linspace(-1, 1, 51))
    print 'Best Pitch: %.3f at %.3f ' % (out)
    sleep(1.0)
    caput('13IDA:QE2:ComputePosOffset12.PROC', 1, wait=True)
    caput('13IDA:QE2:ComputePosOffset34.PROC', 1, wait=True)
    sleep(0.5)
    caput('13IDA:efast_pitch_pid.FBON', 0)
    caput('13IDA:efast_roll_pid.FBON', 0)
    caput('13XRM:edb:use_fb', 0)
#enddef


def save_xrd(name, t=10, ext=1, prefix='13PE1:', timeout=60.0):
    """Save XRD image from Perkin Elmer camera to file
    
    use prefix=dp_pe2: for detector pool camera!

    Parameters
    ----------
    name:     string for sample name
    t:        exposure time in seconds (default = 10)
    ext:      number for file extension (default = 1)
    prefix:   Camera PV prefix ('13PE1:')

    Examples
    --------
    save_xrd('CeO2', t=20)
    """

    caput(prefix+'cam1:Acquire', 0)
    sleep(0.1)

    caput(prefix+'TIFF1:EnableCallbacks', 0)
    caput(prefix+'TIFF1:AutoSave',        0)
    caput(prefix+'TIFF1:FileName',     name)
    caput(prefix+'TIFF1:FileNumber',    ext)
    caput(prefix+'TIFF1:EnableCallbacks', 1)
    caput(prefix+'cam1:ImageMode',        3)

    sleep(0.1)
    acq_time =caget(prefix+'cam1:AcquireTime')

    numimages = int(t*1.0/acq_time)
    caput(prefix+'cam1:NumImages', numimages)

    # expose
    sleep(0.1)
    caput(prefix+'cam1:Acquire', 1)
    sleep(0.5 + max(0.5, 0.5*t))
    t0 = time.time()
    while (1 == caget(prefix+'cam1:Acquire') and
           (time.time()-t0 < timeout)):
        sleep(0.1)
        count += 1
    #endwhile
    print('Acquire Done!')
    sleep(0.1)

    # clean up, returning to short dwell time
    caput(prefix+'TIFF1:WriteFile',       1)
    caput(prefix+'TIFF1:EnableCallbacks', 0)
    sleep(0.5)

    caput(prefix+'cam1:ImageMode', 2)
    sleep(0.5)
    caput(prefix+'cam1:Acquire', 1)
#enddef


def registerLarchPlugin(): # must have a function with this name!
    return ('_scan', {'detector_distance': detector_distance,
                      'move_instrument':   move_instrument,
                      'move_energy':       move_energy,
                      'set_SRSgain':       set_SRSgain,
                      'set_i1amp_gain':    set_i1amp_gain,
                      'set_i0amp_gain':    set_i0amp_gain,
                      'find_max_intensity': find_max_intensity,
                      'set_mono_tilt':     set_mono_tilt,
                      'save_xrd':          save_xrd,
                      'read_stageconfig': read_stageconfig,
                      'move_samplestage': move_samplestage,
                      'test_samplestage': test_samplestage,
                      })
