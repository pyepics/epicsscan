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
    def __init__(self, host, group=None, port=5001, timeout=10,
                 user='Administrator', passwd='Administrator',
                 gather_outputs=('CurrentPosition', 'SetpointPosition')):
        self.host   = host
        self.port   = port
        self.user   = user
        self.passwd = passwd
        self.timeout = timeout
        self.group_name = None
        self.nlines_out = 0
        self.gather_outputs = gather_outputs
        self.linear_template = None
        self.xps = XPS()
        self.ssid = self.xps.TCP_ConnectToServer(host, port, timeout)
        ret = self.xps.Login(self.ssid, user,passwd)
        self.trajectories = {}

        self.ftpconn = ftplib.FTP()

        self.groups = self.read_groups()
        if group is not None:
            self.set_group(group)

    def set_group(self, group):
        if group not in self.groups:
            print("Invalid Group name: %s" % group)
            print("Must be one of ", repr(self.groups.keys()))
            return

        self.group_name = group
        self.positioners = self.groups[group]['positioners']


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
        self.ftpconn.cwd("Config")

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
                pos = [a.strip() for a in words.split(',')]
                for p in pos:
                    if len(p)> 0:
                        groups[p] = {}
                        groups[p]['category'] = cat
                        groups[p]['positioners'] = []

        return groups

    def upload_trajectory_file(self, fname,  data):
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
        self.linear_template = '\n'.join(['', b1, b2, b3])

    def define_line_trajectories(self, axis='X', start=0, stop=1, accel=None,
                                 step=0.001, scantime=10.0, upload=True):
        """defines 'forward' and 'backward' trajectories for a simple 1 element
        line scan in PVT Mode
        """
        if self.group_name is None:
            print("Must set group name first!")
            return
        self.make_linear_template()

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

        ret = True
        if upload:
            ret = False
            try:
                self.upload_trajectory_file('foreward.trj',
                                            self.linear_template % fore_traj)
                self.upload_trajectory_file('backward.trj',
                                            self.linear_template % back_traj)
                ret = True
            except:
                raise ValueError("error uploading trajectory")
        return ret

    def run_trajectory(self, name='foreward', verbose=False, save=True,
                       output_file='Gather.dat'):
        """run trajectory in PVT mode"""
        if self.group_name is None:
            print("Must set group name!")
        traj = self.trajectories.get(name, None)
        if traj is None:
            print("Cannot find trajectory named '%s'" %  name)
            return

        traj_file = '%s.trj'  % name
        axis = traj['axis']
        dtime = traj['pixeltime']

        ramps = [-traj['%sramp' % p] for p in self.positioners]

        self.xps.GroupMoveRelative(self.ssid, self.group_name, ramps)

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
            npulses = self.save_results(output_file, verbose=verbose)
        return npulses

    def abort_scan(self):
        pass

    def move(self, group=None, **kws):
        """move group to supplied position

        """
        if group is None or group not in self.groups:
            group = self.group_name
        if group is None:
            print("Do have a group to move")
            return
        posnames = [p.lower() for p in self.groups[group]['positioners']]
        ret = self.xps.GroupPositionCurrentGet(self.ssid, group, len(posnames))
        print("Move: Current Ret=", ret, group, posnames)
        kwargs = {}
        for k, v in kws.items():
            kwargs[k.lower()] = v

        vals = []
        for i, p in enumerate(posnames):
            if p in kwargs:
                vals.append(kwargs[p])
            else:
                vals.append(ret[i+1])

        self.xps.GroupMoveAbsolute(self.ssid, group, vals)

    def read_gathering(self):
        pass

    def save_results(self,  fname, verbose=False):
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
    xps = XPSTrajectory('164.54.160.180', group='FINE')
    xps.define_line_trajectories(axis='x', start=-2., stop=2., scantime=20, step=0.004)
    print xps.trajectories
    xps.move(-2.0, 0.1, 0)
    time.sleep(0.02)
    xps.run_trajectory(name='foreward', output_file='Out.dat')
