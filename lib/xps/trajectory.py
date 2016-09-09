import time
import ftplib
from cStringIO import StringIO
from XPS_C8_drivers import  XPS


MONO_ACCEL    = {'X': 10.0, 'Y': 10.0, 'THETA': 100.0}
DEFAULT_ACCEL = {'X': 20.0, 'Y': 20.0, 'THETA': 300.0}
MAX_VELO      = {'X': 10.0, 'Y': 10.0, 'THETA':  80.0}

class XPSTrajectory(object):
    """
    XPS trajectory
    """
    traj_folder = 'Public/Trajectories'
    gather_header = '# XPS Gathering Data\n#--------------'
    def __init__(self, host, group='FINE', port=5001, timeout=10,
                 user='Administrator', passwd='Administrator',
                 gather_outputs=('CurrentPosition', 'SetpointPosition')):
        self.host   = host
        self.port   = port
        self.user   = user
        self.passwd = passwd
        self.timeout = timeout
        self.group_name = group
        self.gather_outputs = gather_outputs
        self.xps = XPS()
        self.ssid = self.xps.TCP_ConnectToServer(host, port, timeout)
        ret = self.xps.Login(self.ssid, user,passwd)
        self.trajectories = {}

        self.ftpconn = ftplib.FTP()

        self.all_groups = self.read_groups()
        self.positioners = self.all_groups[group]['positioners']

        self.make_linear_template()

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

    def read_groups(self):
        txt = StringIO()
        self.ftp_connect()
        self.ftpconn.cwd("CONFIG")
        self.ftpconn.retrbinary("RETR system.ini", txt.write)
        self.ftp_disconnect()
        txt.seek(0)
        groups = {}
        mode, this = None, None
        for line in txt.readlines():
            line = line[:-1].strip()
            if line.startswith('[GROUPS]'):
                mode = 'GROUPS'
            elif line.startswith('['):
                mode = None
                words = line[1:].split(']')
                this = words[0]
                if '.' in this:
                    g, p = this.split('.')
                    groups[g]['positioners'].append(p)
            elif mode == 'GROUPS' and len(line) > 3:
                cat, words = line.split('=', 1)
                pos = words.strip().split(',')
                for p in pos:
                    if len(p)> 0:
                        groups[p] = {}
                        groups[p]['category'] = cat
                        groups[p]['positioners'] = []

        return groups

    def upload_trajectoryFile(self, fname,  data):
        self.ftp_connect()
        self.ftpconn.cwd(self.traj_folder)
        self.ftpconn.storbinary('STOR %s' %fname, StringIO(data))
        self.ftp_disconnect()

    def make_linear_template(self):
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
            raise ValueError("error uploading trajectory")
        return ret

    def RunLineTrajectory(self, name='foreward', verbose=False, save=True,
                          outfile='Gather.dat',  debug=False):
        """run trajectory in PVT mode"""
        traj = self.trajectories.get(name, None)
        if traj is None:
            print( 'Cannot find trajectory named %s' %  name)
            return

        traj_file = '%s.trj'  % name
        axis = traj['axis']
        dtime = traj['pixeltime']

        ramps = [-traj['%sramp' % p] for p in self.positioners]

        self.xps.GroupMoveRelative(self.ssid, 'FINE', ramps)

        g_output = []
        g_titles = []
        for out in self.gather_outputs:
            g_output.append('%s.%s.%s' % (self.group_name, axis, out))
            g_titles.append('%s.%s' % (axis, out))

        self.gather_titles = "%s\n#%s\n" % (self.gather_header, " ".join(g_titles))
        ret = self.xps.GatheringReset(self.ssid)
        self.xps.GatheringConfigurationSet(self.ssid, g_output)

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
        ret, npulses, nx = self.xps.GatheringCurrentNumberGet(self.ssid)
        counter = 0
        while npulses < 1 and counter < 5:
            counter += 1
            time.sleep(1.50)
            ret, npulses, nx = self.xps.GatheringCurrentNumberGet(self.ssid)
            print( 'Had to do repeat XPS Gathering: ', ret, npulses, nx)

        ret, buff = self.xps.GatheringDataMultipleLinesGet(self.ssid, 0, npulses)

        if ret < 0:  # gathering too long: need to read in chunks
            print( 'Need to read Data in Chunks!!!')
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
                    print('looks like something is wrong with the XPS!')
                    break
            print(' -- will use %i Chunks for %i Pulses ' % (Nchunks, npulses))
            buff = [xbuff]
            for i in range(1, Nchunks):
                ret, xbuff = self.xps.GatheringDataMultipleLinesGet(self.ssid, i*nx, nx)
                buff.append(xbuff)
            ret, xbuff = self.xps.GatheringDataMultipleLinesGet(self.ssid, Nchunks*nx,
                                                                npulses-Nchunks*nx)
            buff.append(xbuff)
            buff = ''.join(buff)

        obuff = buff[:]
        for x in ';\r\t':
            obuff = obuff.replace(x,' ')
        f = open(fname, 'w')
        f.write(self.gather_titles)
        f.write(obuff)
        f.close()
        nlines = len(obuff.split('\n')) - 1
        if verbose:
            print('Wrote %i lines, %i bytes to %s' % (nlines, len(buff), fname))
        self.nlines_out = nlines
        return npulses


if __name__ == '__main__':
    xps = XPSTrajectory()
    xps.DefineLineTrajectories(axis='x', start=-2., stop=2., scantime=20, step=0.004)
    print xps.trajectories
    xps.Move(-2.0, 0.1, 0)
    time.sleep(0.02)
    xps.RunLineTrajectory(name='foreward', outfile='Out.dat')
