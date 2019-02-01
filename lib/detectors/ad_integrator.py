import os, sys, time, json
import numpy as np
from epicsscan.scandb import ScanDB

from pyFAI.azimuthalIntegrator import AzimuthalIntegrator

MAXVAL = 2**32 - 2**15

class AD_Integrator(object):
    """1D integrator"""
    def __init__(self,  suffix='h5', **kws):
        self.scandb = ScanDB()
        self.folder = ''
        self.label = ''
        self.suffix = suffix
        self.sleep_time = 1.0
        self.set_state('idle')

    def set_state(self, state):
        self.scandb.set_info('xrd_1dint_status', state.lower())

    def get_state(self, state):
        return self.scandb.set_info('xrd_1dint_status').lower()

    def read_config(self):
        calfile = self.scandb.get_info('xrd_calibration')
        self.label = self.scandb.get_info('xrd_1dint_label')
        self.folder = self.scandb.get_info('map_folder')
        if self.folder.endswith('/'):
            self.folder = self.folder[:-1]

        calib = json.loads(self.scandb.get_detectorconfig(calfile).text)
        self.integrator = AzimuthalIntegrator(**calib)

    def save_1dint(self, h5file, outfile):
        t0 = time.time()
        xrdfile = h5py.File(h5file, 'r')
        data = xrdfile['/entry/data/data']
        if data.shape[1] > data.shape[2]:
            data = data[1:, 3:-3, 1:-1]
        else:
            data = data[1:, 1:-1, 3:-3]

        nframes, nx, ny = data.shape
        xrdfile.close()
        integrate = self.integrator.integrate1d
        opts = dict(method='csr',unit='q_A^-1',
                    correctSolidAngle=True,
                    polarization_factor=0.999)
        dat = []
        for i in range(nframes):
            img = data[i, :, :]
            img[np.where(img>MAXVAL)] = 0
            q, x = integrate(img[::-1, :], 2048, **opts)
            if i == 0:
                dat.append(q)
            dat.append(x)
        dat = np.array(dat)
        _path, fname = os.path.split(outfile)
        print("writing 1D data: %s, %.2f sec" %  (fname, time.time()-t0))
        np.save(outfile, dat)

    def integrate(self):
        fname = '%s*.%s' % (self.label, self.suffix)
        xrdfiles = glob(os.path.join(self.folder, fname))
        for xfile in sorted(xrdfiles):
            outfile = xfile.replace(self.suffix, '.npy')
            if not os.path.exists(outfile):
                self.save_1dint(xfile, outfile)

    def run(self):
        while True:
            time.sleep(self.sleep_time)
            state = self.get_state()
            if state.startswith('starting'):
                self.read_config()
                self.set_state('running')
            elif state.startswith('running'):
                self.integrate()
            elif state.startswith('finishing'):
                self.integrate()
                self.set_state('idle')
                self.map_folder = ''
            elif state.startswith('idle'):
                time.sleep(5*self.sleep_time)
            elif state.startswith('quit'):
                return
