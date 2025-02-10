#!/usr/bin/env python
"""
Output data file layer for Step Scan

Different output formats can be supported, but the basic file
defined here is a plaintext, ASCII format using newlines as
delimiters and '#' as comment characters, and a fairly strict,
parsable format.

ScanFile supports several methods:

  open()
  close()
  write_extrapvs()
  write_comments()
  write_legend()
  write_timestamp()
  write_data()

which  can be overridden to create a new Output file type
"""
import numpy as np
from .file_utils import new_filename, get_timestamp, fix_filename

COM1 = '#'
COM2 = '/'*3 + '  Users Comments  ' + '/'*3
COM3 = '-'*65
SEP = ' || '   # separater between value, pvname in header
FILETOP = '#XDI/1.1    Epics StepScan File'

class StepScanData():
    """
    Holds data as read from a Scan Data File.
    """
    def __init__(self, filename=None, **kws):
        self.filename = filename
        self.extra_pvs = []
        self.comments  = []
        self.column_keys    = []
        self.column_names   = []
        self.column_units   = []
        self.column_pvnames = []
        self.breakpoints    = []
        self.breakpoint_times = []
        self.__arraymap = None
        self.start_time = None
        self.stop_time = None
        self.data = []
        self._valid = False
        if filename is not None:
            self.read(filename)

    def get_data(self, key):
        """get positioner or detector array either by key, name, or index
        key can be any of (case-insensitive):
            column number, starting at 0
            column label, 'p1', 'd1', etc
            name of column
            pvname of column
        """
        # cache lower-case version of all keys and names
        if self.__arraymap is None:
            self.__arraymap = {}
            for a in (self.column_keys, self.column_names, self.column_pvnames):
                for i, nam in enumerate(a):
                    self.__arraymap[nam.lower()] = i
        #
        if (isinstance(key, int) and (key > -1) and
           (key < len(self.column_keys))):
            icol = key
        else:
            icol = self.__arraymap.get(key.lower(), None)

        if icol is None:
            print(f"cannot find column {key}")
            return None
        return self.data[icol]

    def read(self, filename=None):
        "read file"
        if filename is not None:
            self.filename = filename
        self._valid = False
        with open(self.filename, 'r') as fh:
            lines = fh.readlines()

        line0 = lines.pop(0)
        if not line0.startswith(FILETOP):
            print(f"'{self.filename}' is not a valid Epics Scan file")
            return

        def split_header(line):
            w = [k.strip() for k in line.replace('#', '').split(':', 1)]
            if len(w) == 1:
                w.append('')
            return w
        mode = None
        extras = {}
        modes = {'Time': 'comment', '----': 'data',
                 'Legend Start': 'legend', 'Legend End': 'legend_end',
                 'ExtraPVs Start': 'extras', 'ExtraPVs End': 'extras_end'}
        for line in lines:
            if line.startswith(COM1):
                key, val = split_header(line[:-1])
                if key.startswith('----'):
                    key = '----'
                if key in modes:
                    mode = modes[key]
                    if mode == 'comment':
                        self.stop_time  = val
                        if self.start_time is None:
                            self.start_time = val
                    elif mode == 'extras':
                        self.breakpoints.append(len(self.data))
                        self.breakpoint_times.append(self.stop_time)
                    elif mode == 'extras_end':
                        self.extra_pvs.append(extras)
                        extras = {}
                    continue
                if mode == 'comment':
                    cmt = line[:-1].strip()
                    if cmt.startswith('#'):
                        cmt = line[1:].strip()
                    self.comments.append(cmt)
                elif mode in ('legend', 'extras'):
                    words = [w.strip() for w in val.split(SEP)]
                    if len(words) == 1:
                        words.append('')
                    if mode == 'extras':
                        extras[key] = (words[0], words[1])
                    else:
                        if len(words) == 2: words.append('')
                        self.column_keys.append(key)
                        self.column_names.append(words[0])
                        self.column_units.append(words[1])
                        self.column_pvnames.append(words[2])

            else: # data!
                self.data.append([float(i) for i in line[:-1].split()])
        #
        self.comments = '\n'.join(self.comments)
        self.data = np.array(self.data).transpose()
        self._valid = True

class ScanFile():
    """base Scan File -- intended to be inherited and
    overrwritten for multiple ScanFile types (ASCII, HDF5) to be
    supported with compatible methods
    """
    def __init__(self, name=None, scan=None):
        self.filename = name
        self.fh = None
        self.scan = scan

    def open_for_write(self, filename=None, mode='a'):
        """open file for write or append,
        ensuring the filename is auto-incremented so as to
        not clobber an existing file name"""
        if filename is not None:
            self.filename  = filename
        if 'a' in mode or 'w' in mode:
            self.filename = new_filename(fix_filename(self.filename))

        if self.fh is not None:
            self.fh.close()
        self.fh = open(self.filename, mode)
        return self.fh

    def check_writeable(self):
        "check that output file is open and writeable"
        if self.fh is None:
            return False
        writable = getattr(self.fh, 'writable', None)
        if writable is not None:
            return writable()
        try:
            return (not self.fh.closed and
                    ('a' in self.fh.mode or 'w' in self.fh.mode))
        except:
            return False

    def flush(self):
        "flush file"
        if self.fh is not None:
            self.fh.flush()

    def write(self, s):
        "write to file"
        if self.fh is not None:
            self.fh.write(s)

    def close(self):
        "close file"
        if self.fh is not None:
            self.fh.close()

    def write_extrapvs(self):
        "write extra PVS"
        return

    def write_comments(self):
        "write legend"
        return

    def write_legend(self):
        "write legend"
        return

    def write_timestamp(self):
        "write timestamp"
        return

    def write_data(self, breakpoint=0, clear=False):
        "write data"
        return

class ASCIIScanFile(ScanFile):
    """basis ASCII Column File, line-ending delimited,
    using '#' for comment lines
    and a format derived from XDI
    """
    num_format = "% 15f"
    version = '2.0'
    def __init__(self, name=None, scan=None, comments=None,
                 auto_increment=True):
        ScanFile.__init__(self, name=name, scan=scan)
        if name is None:
            self.filename = 'test.dat'
        self.auto_increment = auto_increment
        self.comments = comments

    def write_lines(self, buff):
        "write array of text lines"
        if not self.check_writeable():
            self.open_for_write(mode='a')
            self.write(f"{FILETOP} / {self.version}\n")
        buff.append('')
        self.write('\n'.join(buff))
        self.flush()

    def write_extrapvs(self):
        "write extra PVS"
        extra_pvs = self.scan.read_extra_pvs()
        if extra_pvs is None or len(extra_pvs) < 1:
            return

        out = [f'{COM1} ExtraPVs.Start: Family.Member: Value | PV']
        for desc, pvname, val in extra_pvs:
            if not isinstance(val, str):
                val = repr(val)
            # require a '.' in the description!!
            if '.' not in desc:
                isp = desc.find(' ')
                if isp > 0:
                    desc = f"{desc[:isp]}.{desc[isp+1:]}"
                else:
                    desc = f"{desc}.Value"
                desc = fix_filename(desc)
            sthis = f"{COM1} {desc}: {val}"
            if len(sthis) < 42:
                sthis = (sthis + ' '*42)[:42]
            out.append(f"{sthis} {SEP} {pvname}")
        out.append(f'{COM1} ExtraPVs.End: here')
        self.write_lines(out)

    def write_scanparams(self):
        "write scan parameters"
        s = self.scan
        if 'xafs' not in s.scantype.lower():
            return
        out = [f'{COM1} ScanParameters.Start: Scan.Member: Value']
        out.append(f'{COM1} ScanParameters.ScanType: {s.scantype}')
        # regfmt = '%9.3f, %9.3f, %9.3f  %s  %.2f'
        if 'xafs' in s.scantype.lower():
            elem = getattr(s, 'elem', 'Unknown')
            edge = getattr(s, 'edge', 'Unknown')
            out.append(f'{COM1} ScanParameters.element: {elem}')
            out.append(f'{COM1} ScanParameters.edge: {edge}')
            out.append(f'{COM1} ScanParameters.E0: {s.e0:.3f}')
            out.append(f'{COM1} ScanParameters.Legend:  Start, Stop, Step, K-space, Time')
            for ireg, reg in enumerate(s.regions):
                start, stop, npts, rel, e0, use_k, dt0, dt1, dtw = reg
                step = abs(stop-start)/(npts-1.0)
                regtxt = f"{start:9.3f}, {stop:9.3f}, {step:9.3f} {use_k} {rel} {e0} {dt0:.2f}"
                if dt1 is not None:
                    regtxt = f"{regtxt} .. {dt1:.2f} (weight={dtw})"
                out.append(f"{COM1} ScanParameters.Region{ireg+1}:  {regtxt}")
        out.append(f"{COM1} ScanParameters.End: ~~~~~~~~~~")
        self.write_lines(out)

    def write_timestamp(self, label='Now'):
        "write timestamp"
        self.write_lines([f"{COM1} Scan.{label}: {get_timestamp()}"])

    def write_comments(self):
        "write comment lines"
        if self.comments is None:
            print("Warning: no comments to write!")
            return
        self.write_lines([f"{COM1} {COM2}"])
        self.write_lines([f"{COM1} {line}" for line in self.comments.split('\n')])

    def write_legend(self):
        "write legend"
        cols = []
        icol = 0
        out = [f"{COM1} Legend.Start: Column.N: Name  units || EpicsPV"]
        for lvars  in ((self.scan.positioners, 'unknown'),
                      (self.scan.counters, 'counts')):
            objs, objunits = lvars
            for obj in objs:
                icol += 1
                key = f"{COM1} Column.{icol}"
                units =  objunits
                pv = getattr(obj, 'pv', None)
                pvname = getattr(obj, 'pvname', None)
                if pvname is None and pv is not None:
                    pvname = pv.pvname
                if pvname is None:
                    pvname = ''
                if obj.units in (None, 'None', ''):
                    if pv is not None:
                        units = getattr(pv, 'units', None)
                else:
                    units = obj.units
                if units in (None, 'None', ''):
                    units = objunits
                lab = fix_filename(obj.label.strip())
                sthis = f"{key}: {lab} {units}"
                extra = getattr(obj, 'extra_label', '')
                if len(extra) > 0:
                    sthis = sthis + f" = {extra}"
                if len(sthis) < 45:
                    sthis = (sthis + ' '*45)[:45]
                sthis = f"{sthis} {SEP} {pvname}"
                out.append(sthis)
                cols.append(lab)

        out.append(f"{COM1} Legend.End: ~~~~~~~~~~")
        self.write_lines(out)
        self.array_labels = [f"{c:>13s}" for c in cols]

    def write_data(self, breakpoint=0, clear=False, close_file=False, verbose=False):
        "write data"
        if breakpoint == 0:
            self.write_timestamp(label='start_time')
            self.write_legend()
            return
        self.write_timestamp(label='end_time')
        self.write_extrapvs()
        self.write_scanparams()
        self.write_comments()

        out = [f"{COM1}------------------------------",
               f"{COM1} {' '.join(self.array_labels)}"]
        npts_all = [len(c.buff) for c in self.scan.counters]
        npts_all.append(len(self.scan.pos_actual))
        for i in range(max(npts_all)):
            words =  self.scan.pos_actual[i][:]
            for c in self.scan.counters:
                try:
                    val = c.buff[i]
                except:
                    val = -1.0
                words.append(val)
            try:
                thisline = ' '.join([f"{w: 15f}" for w in words])
            except:
                thisline = ' '.join([repr(w) for w in words])
            out.append(thisline)

        self.write_lines(out)
        if clear:
            self.scan.clear_data()

        if close_file:
            self.close()
            if verbose:
                print(f"Wrote and closed {self.filename}")

    def read(self, filename=None):
        return StepScanData(filename)
