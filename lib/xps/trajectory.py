import time
import sys
import ftplib
import logging
from cStringIO import StringIO
from string import printable
from copy import deepcopy
from ..debugtime import debugtime
from .config import config
from XPS_C8_drivers import  XPS

##
## used methods for collector.py
##    abortScan, clearabort
##    done ftp_connect
##    done ftp_disconnect
##
## mapscan:   Build (twice!)
## linescan:  Build , clearabort
## ExecTraj;  Execute(),   building<attribute>, executing<attribute>
## WriteTrajData:  Read_FTP(), SaveGatheringData()
##
## need to have env and ROI written during traj scan:
##   use a separate thread for ROI and ENV, allow
##   XY trajectory to block.

MONO_ACCEL = {'X': 10.0, 'Y': 10.0, 'THETA': 100.0}

DEFAULT_ACCEL = {'X': 20.0, 'Y': 20.0, 'THETA': 300.0}
MAX_VELO      = {'X': 10.0, 'Y': 10.0, 'THETA':  80.0}


class XPSTrajectory(object):
    """
    XPS trajectory
    """
    def __init__(self, host=None, user=None, passwd=None,
                 group=None, positioners=None, mode=None, type=None):
        self.host = host or config.host
        self.user = user or config.user
        self.passwd = passwd or config.passwd
        self.group_name = group or config.group_name
        self.positioners = positioners or config.positioners
        self.positioners = tuple(self.positioners.replace(',', ' ').split())

        self.make_template()

        gout = []
        gtit = []
        for pname in self.positioners:
            for out in config.gather_outputs:
                gout.append('%s.%s.%s' % (self.group_name, pname, out))
                gtit.append('%s.%s' % (pname, out))
        self.gather_outputs = gout
        self.gather_titles  = "%s\n#%s\n" % (config.gather_titles,
                                          "  ".join(gtit))

        # self.gather_titles  = "%s %s\n" % " ".join(gtit)

        self.xps = XPS()
        self.ssid = self.xps.TCP_ConnectToServer(self.host, config.port, config.timeout)
        ret = self.xps.Login(self.ssid, self.user, self.passwd)
        self.trajectories = {}

        self.ftpconn = ftplib.FTP()

        self.nlines_out = 0

        self.xps.GroupMotionDisable(self.ssid, self.group_name)
        time.sleep(0.1)
        self.xps.GroupMotionEnable(self.ssid, self.group_name)

        for i in range(64):
            self.xps.EventExtendedRemove(self.ssid,i)


    def ftp_connect(self):
        self.ftpconn.connect(self.host)
        self.ftpconn.login(self.user,self.passwd)
        self.FTP_connected = True

    def ftp_disconnect(self):
        "close ftp connnection"
        self.ftpconn.close()
        self.FTP_connected=False

    def upload_trajectoryFile(self, fname,  data):
        self.ftp_connect()
        self.ftpconn.cwd(config.traj_folder)
        self.ftpconn.storbinary('STOR %s' %fname, StringIO(data))
        self.ftp_disconnect()
        # print 'Uploaded trajectory: ', fname

    def make_template(self):
        # line1
        b1 = ['%(ramptime)f']
        b2 = ['%(scantime)f']
        b3 = ['%(ramptime)f']
        for p in self.positioners:
            b1.append('%%(%sramp)f' % p)
            b1.append('%%(%svelo)f' % p)
            b2.append('%%(%sdist)f' % p)
            b2.append('%%(%svelo)f' % p)
            b3.append('%%(%sramp)f' % p)
            b3.append('%(zero)f')
        b1 = ', '.join(b1)
        b2 = ', '.join(b2)
        b3 = ', '.join(b3)
        self.template = '\n'.join(['', b1, b2, b3])

    def DefineLineTrajectories(self, axis='X', start=0, stop=1, accel=None,
                               step=0.001, scantime=10.0, **kws):
        """defines 'forward' and 'backward' trajectories for a simple 1 element
        line scan in PVT Mode"""
        axis =  axis.upper()
        if accel is None:
            accel = DEFAULT_ACCEL[axis]

        dist     = (stop - start)*1.0
        sign     = dist/abs(dist)
        scantime = abs(scantime)
        pixeltime = scantime * step / abs(dist)
        velo      = dist / scantime
        if velo > MAX_VELO[axis]:
            velo = MAX_VELO[axis]
        ramptime = abs(velo / accel)
        ramp     = 0.5 * velo * ramptime
        fore_traj = {'scantime':scantime, 'axis':axis, 'accel': accel,
                     'ramptime': ramptime, 'pixeltime': pixeltime,
                     'zero': 0.}
        # print 'Scan Times: ', scantime, pixeltime, (dist)/(step), accel
        # print 'ACCEl ' , accel, velo, ramptime, ramp
        this = {'start': start, 'stop': stop, 'step': step,
                'velo': velo, 'ramp': ramp, 'dist': dist}
        for attr in this.keys():
            for ax in self.positioners:
                if ax == axis:
                    fore_traj["%s%s" % (ax, attr)] = this[attr]
                else:
                    fore_traj["%s%s" % (ax, attr)] = 0.0

        back_traj = fore_traj.copy()
        for ax in self.positioners:
            for attr in ('velo', 'ramp', 'dist'):
                back_traj["%s%s" % (ax, attr)] *= -1.0
            back_traj["%sstart" % ax] = this['stop']
            back_traj["%sstp" % ax]   = this['start']

        self.trajectories['backward'] = back_traj
        self.trajectories['foreward'] = fore_traj

        ret = False
        try:
            self.upload_trajectoryFile('foreward.trj', self.template % fore_traj)
            self.upload_trajectoryFile('backward.trj', self.template % back_traj)
            ret = True
        except:
            logging.exception("error uploading trajectory")
        return ret

    def RunLineTrajectory(self, name='foreward', verbose=False, save=True,
                          outfile='Gather.dat',  debug=False):
        """run trajectory in PVT mode"""
        traj = self.trajectories.get(name, None)
        if traj is None:
            print 'Cannot find trajectory named %s' %  name
            return

        traj_file = '%s.trj'  % name
        axis = traj['axis']
        dtime = traj['pixeltime']

        ramps = [-traj['%sramp' % p] for p in self.positioners]

        self.xps.GroupMoveRelative(self.ssid, 'FINE', ramps)

        # print '=====Run Trajectory =  ', traj, axis, ramps, traj_file

        self.gather_outputs = []
        gather_titles = []
        for out in config.gather_outputs:
            self.gather_outputs.append('%s.%s.%s' % (self.group_name, axis, out))
            gather_titles.append('%s.%s' % (axis, out))

        self.gather_titles  = "%s\n#%s\n" % (config.gather_titles,
                                             "  ".join(gather_titles))

        # print '==Gather Titles== ',  self.gather_titles
        # print '==Gather Outputs==',  self.gather_outputs

        ret = self.xps.GatheringReset(self.ssid)
        self.xps.GatheringConfigurationSet(self.ssid, self.gather_outputs)

        ret = self.xps.MultipleAxesPVTPulseOutputSet(self.ssid, self.group_name,
                                                     2, 3, dtime)
        ret = self.xps.MultipleAxesPVTVerification(self.ssid, self.group_name, traj_file)

        buffer = ('Always', '%s.PVT.TrajectoryPulse' % self.group_name,)
        ret = self.xps.EventExtendedConfigurationTriggerSet(self.ssid, buffer,
                                                          ('0','0'), ('0','0'),
                                                          ('0','0'), ('0','0'))

        ret = self.xps.EventExtendedConfigurationActionSet(self.ssid,  ('GatheringOneData',),
                                                         ('',), ('',),('',),('',))

        eventID, m = self.xps.EventExtendedStart(self.ssid)

        ret = self.xps.MultipleAxesPVTExecution(self.ssid, self.group_name, traj_file, 1)
        ret = self.xps.EventExtendedRemove(self.ssid, eventID)
        ret = self.xps.GatheringStop(self.ssid)

        npulses = 0
        if save:
            npulses = self.SaveResults(outfile, verbose=verbose)
        return npulses

    def abortScan(self):
        pass

    def Move(self, xpos=None, ypos=None, tpos=None):
        "move XY positioner to supplied position"
        ret = self.xps.GroupPositionCurrentGet(self.ssid, 'FINE', 3)
        if xpos is None:  xpos = ret[1]
        if ypos is None:  ypos = ret[2]
        if tpos is None:  tpos = ret[3]
        self.xps.GroupMoveAbsolute(self.ssid, 'FINE', (xpos, ypos, tpos))

    def ReadGatheringPulses(self):
        ret, npulses, nx = self.xps.GatheringCurrentNumberGet(self.ssid)
        if npulses < 1:
            time.sleep(1)
            ret, npulses, nx = self.xps.GatheringCurrentNumberGet(self.ssid)
        return npulses

    def SaveResults(self,  fname, verbose=False):
        """read gathering data from XPS
        """
        # self.xps.GatheringStop(self.ssid)
        # db = debugtime()
        ret, npulses, nx = self.xps.GatheringCurrentNumberGet(self.ssid)
        counter = 0
        while npulses < 1 and counter < 5:
            counter += 1
            time.sleep(1.50)
            ret, npulses, nx = self.xps.GatheringCurrentNumberGet(self.ssid)
            print 'Had to do repeat XPS Gathering: ', ret, npulses, nx

        # db.add(' Will Save %i pulses , ret=%i ' % (npulses, ret))
        ret, buff = self.xps.GatheringDataMultipleLinesGet(self.ssid, 0, npulses)
        # db.add('MLGet ret=%i, buff_len = %i ' % (ret, len(buff)))

        if ret < 0:  # gathering too long: need to read in chunks
            print 'Need to read Data in Chunks!!!'  # how many chunks are needed??
            Nchunks = 3
            nx    = int( (npulses-2) / Nchunks)
            ret = 1
            while True:
                time.sleep(0.1)
                ret, xbuff = self.xps.GatheringDataMultipleLinesGet(self.ssid, 0, nx)
                if ret == 0:
                    break
                Nchunks = Nchunks + 2
                nx      = int( (npulses-2) / Nchunks)
                if Nchunks > 10:
                    print 'looks like something is wrong with the XPS!'
                    break
            print  ' -- will use %i Chunks for %i Pulses ' % (Nchunks, npulses)
            # db.add(' Will use %i chunks ' % (Nchunks))
            buff = [xbuff]
            for i in range(1, Nchunks):
                ret, xbuff = self.xps.GatheringDataMultipleLinesGet(self.ssid, i*nx, nx)
                buff.append(xbuff)
                # db.add('   chunk %i' % (i))
            ret, xbuff = self.xps.GatheringDataMultipleLinesGet(self.ssid, Nchunks*nx,
                                                                npulses-Nchunks*nx)
            buff.append(xbuff)
            buff = ''.join(buff)
            # db.add('   chunk last')

        obuff = buff[:]
        for x in ';\r\t':
            obuff = obuff.replace(x,' ')
        # db.add('  data fixed')
        f = open(fname, 'w')
        f.write(self.gather_titles)
        f.write(obuff)
        f.close()
        nlines = len(obuff.split('\n')) - 1
        if verbose:
            print 'Wrote %i lines, %i bytes to %s' % (nlines, len(buff), fname)
        self.nlines_out = nlines
        # db.show()
        return npulses


if __name__ == '__main__':
    xps = XPSTrajectory()
    xps.DefineLineTrajectories(axis='x', start=-2., stop=2., scantime=20, step=0.004)
    print xps.trajectories
    xps.Move(-2.0, 0.1, 0)
    time.sleep(0.02)
    xps.RunLineTrajectory(name='foreward', outfile='Out.dat')
