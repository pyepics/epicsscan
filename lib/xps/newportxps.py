import time
import ftplib
import socket

from cStringIO import StringIO
from ConfigParser import  ConfigParser

from XPS_C8_drivers import XPS

from collections import OrderedDict

class XPSError(Exception):
    """XPS Controller Exception"""
    def __init__(self, msg,*args):
        self.msg = msg
    def __str__(self):
        return str(self.msg)

IDLE, ARMING, ARMED, RUNNING, COMPLETE, WRITING, READING = \
      'IDLE', 'ARMING', 'ARMED', 'RUNNING', 'COMPLETE', 'WRITING', 'READING'

class NewportXPS:
    gather_header = '# XPS Gathering Data\n#--------------'
    def __init__(self, host, group=None,
                 user='Administrator', passwd='Administrator',
                 port=5001, timeout=10,
                 gather_outputs=('CurrentPosition', 'SetpointPosition')):

        socket.setdefaulttimeout(5.0)
        try:
            host = socket.gethostbyname(host)
        except:
            raise ValueError, 'Could not resolve XPS name %s' % host
        self.host = host
        self.port = port
        self.user = user
        self.passwd = passwd
        self.timeout = timeout

        self.gather_outputs = gather_outputs

        self.trajectories = {}
        self.traj_state = IDLE
        self.traj_group = None
        self.traj_file = None
        self.traj_positioners = None

        self.ftpconn = ftplib.FTP()
        self._sid = None
        self._xps = XPS()
        self.connect()

        if group is not None:
            self.set_trajectory_group(group)

    def status_report(self):
        """return printable status report"""
        err, uptime = self._xps.ElapsedTimeGet(self._sid)
        boottime = time.time() - uptime
        out = ["# XPS host:     %s (%s)" % (self.host, socket.getfqdn(self.host)),
               "# Firmware:     %s" % self.firmware_version,
               "# Current Time: %s " % time.ctime(),
               "# Last Reboot:  %s" % time.ctime(boottime),
               ]

        out.append("# Groups and Stages")
        hstat = self.get_hardware_status()
        perrs = self.get_positioner_errors()

        for groupname, status in self.get_group_status().items():
            this = self.groups[groupname]
            out.append("%s: (%s):  Status: %s" %
                       (groupname, this['category'], status))
            for pos in this['positioners']:
                stagename = '%s.%s' % (groupname, pos)
                stage = self.stages[stagename]
                out.append("   %s (%s)"  % (stagename, stage['type']))
                out.append("     Hardware Status: %s"  % (hstat[stagename]))
                out.append("     Positioner Errors: %s"  % (perrs[stagename]))

        out.append("#########################################")
        return "\n".join(out)

    def ftp_connect(self):
        """open ftp connection"""
        self.ftpconn.connect(self.host)
        self.ftpconn.login(self.user, self.passwd)

    def ftp_disconnect(self):
        "close ftp connnection"
        self.ftpconn.close()

    def connect(self):
        self._sid = self._xps.TCP_ConnectToServer(self.host,
                                                  self.port, self.timeout)
        try:
            self._xps.Login(self._sid, self.user, self.passwd)
        except:
            raise XPSError('Login failed for %s' % self.host)

        err, val = self._xps.FirmwareVersionGet(self._sid)
        self.firmware_version = val

        if 'Q8' in self.firmware_version:
            self.ftphome = ''
        else:
            self.ftphome = '/Admin'

        self.read_systemini()
        self.read_errorcodes()

    def read_errorcodes(self):
        err, ret = self._xps.ErrorListGet(self._sid)
        self.errcodes = OrderedDict()
        for codeline in ret.split(';'):
            if ':' in codeline:
                ecode, message = codeline.split(':', 1)
                ecode = ecode.replace('Error', '').strip()
                message = message.strip()
                self.errcodes[ecode] = message

    def format_error(self, ecode):
        if isinstance(ecode, int):
            ecode = '%i' % ecode
        if ecode == '0':
            return "[OK]"
        elif ecode in self.errcodes:
            return "%s [Error %s]" % (self.errcodes[ecode], ecode)
        return "[Error %s]" % (ecode)


    def save_systemini(self, fname='system.ini'):
        """
        save system.ini to disk
        Parameters:
        fname  (string): name of file to save to ['system.ini']
        """
        self.ftp_connect()
        self.ftpconn.cwd('%s/Config' % self.ftphome)
        output = []
        x = self.ftpconn.retrbinary('RETR system.ini', output.append)
        fout = open(fname, 'w')
        fout.write(''.join(output))
        fout.close()
        self.ftp_disconnect()

    def save_stagesini(self, fname='stages.ini'):
        """save stages.ini to disk

        Parameters:
           fname  (string): name of file to save to ['stages.ini']
        """
        self.ftp_connect()
        self.ftpconn.cwd('%s/Config' % self.ftphome)
        output = []
        x = self.ftpconn.retrbinary('RETR stages.ini', output.append)
        fout = open(fname, 'w')
        fout.write(''.join(output))
        fout.close()
        self.ftp_disconnect()

    def read_systemini(self):
        """read group info from system.ini"""

        self.ftp_connect()
        self.ftpconn.cwd('%s/Config' % self.ftphome)

        txt = StringIO()
        self.ftpconn.retrbinary("RETR system.ini", txt.write)
        self.ftp_disconnect()
        txt.seek(0)
        lines = txt.readlines()
        self.sysconf = ''.join(lines)

        sconf = ConfigParser()
        sconf.readfp(StringIO(self.sysconf))

        self.stages= OrderedDict()

        for sect in sconf.sections():
            if 'plugnumber' in sconf.options(sect):
                self.stages[sect] = {'type': sconf.get(sect, 'stagename')}

        self.groups = groups = OrderedDict()
        mode, this = None, None
        pvtgroups = []
        for line in lines:
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
                        if cat.startswith('Multiple'):
                            pvtgroups.append(p)

        if len(pvtgroups) == 1:
            self.set_trajectory_group(pvtgroups[0])

        for sname, data in self.stages.items():
            ret = self._xps.PositionerMaximumVelocityAndAccelerationGet(self._sid, sname)
            data['max_velo']  = ret[1]
            data['max_accel'] = ret[2]
        return groups


    def upload_trajectory(self, filename,  text):
        """upload text of trajectory file

        Arguments:
        ----------
           filename (str):  name of trajectory file
           text  (str):   full text of trajectory file
        """
        self.ftp_connect()
        self.ftpconn.cwd('%s/Public/Trajectories' % self.ftphome)
        self.ftpconn.storbinary('STOR %s' % filename, StringIO(text))
        self.ftp_disconnect()

    def set_trajectory_group(self, group):
        """set group name for upcoming trajectories"""
        valid = False
        if group in self.groups:
            if self.groups[group]['category'].startswith('Multiple'):
                valid = True

        if not valid:
            pvtgroups = []
            for gname, group in self.groups.items():
                if group['category'].startswith('Multiple'):
                    pvtgroups.append(gname)
            pvtgroups = ', '.join(pvtgroups)
            msg = "'%s' cannot be a trajectory group, must be one of %s"
            raise XPSError(msg % (group, pvtgroups))

        self.traj_group = group
        self.traj_positioners = self.groups[group]['positioners']

        try:
            self.disable_group(self.traj_group)
        except XPSError:
            pass

        time.sleep(0.1)
        self.enable_group(self.traj_group)
        for i in range(64):
            self._xps.EventExtendedRemove(self._sid, i)


    def _group_act(self, method, group=None, action='doing something with'):
        """wrapper for many group actions"""
        if self._sid is None:
            self.connect()
        method = getattr(self._xps, method)
        if group is None:
            for group in self.groups:
                err, ret = method(self._sid, group)
                if err is not 0:
                    err = self.format_error(err)
                    raise XPSError("%s group '%s', %s" % (action, group, err))
        elif group in self.groups:
            err, ret = method(self._sid, group)
            if err is not 0:
                err = self.format_error(err)
                raise XPSError("%s group '%s', %s" % (action, group, err))
        else:
            raise ValueError("Group '%s' not found" % group)


    def initialize_group(self, group=None, with_encoder=True, home=False):
        """
        initialize groups, optionally homing each.

        Parameters:
            with_encoder (bool): whethter to initialize with encoder [True]
            home (bool): whether to home all groups [False]
        """

        method = 'GroupInitialize'
        if with_encoder:
            method  = 'GroupInitializeWithEncoderCalibration'
        self._group_act(method, group=group, action='initializing')
        if home:
            self.home_group(group=group)


    def home_group(self, group=None):
        """
        home group

        Parameters:
            group (None or string): name of group to home [None]

        Notes:
            if group is `None`, all groups will be homed.
        """
        self._group_act('GroupHomeSearch', group=group, action='homing')

    def enable_group(self, group=None):
        """enable group

        Parameters:
            group (None or string): name of group to enable [None]

        Notes:
            if group is `None`, all groups will be enabled.
        """
        self._group_act('GroupMotionEnable', group=group, action='enabling')


    def disable_group(self, group=None):
        """disable group

        Parameters:
            group (None or string): name of group to enable [None]

        Notes:
            if group is `None`, all groups will be enabled.
        """
        self._group_act('GroupMotionDisable', group=group, action='disabling')

    def get_group_status(self):
        """
        get dictionary of status for each group
        """
        out = OrderedDict()
        for group in self.groups:
            err, stat = self._xps.GroupStatusGet(self._sid, group)
            err, val = self._xps.GroupStatusStringGet(self._sid, stat)
            out[group] = val
        return out

    def get_hardware_status(self):
        """
        get dictionary of hardware status for each stage
        """
        out = OrderedDict()
        for stage in self.stages:
            if stage in ('', None): continue
            err, stat = self._xps.PositionerHardwareStatusGet(self._sid, stage)
            err, val = self._xps.PositionerHardwareStatusStringGet(self._sid, stat)
            out[stage] = val
        return out

    def get_positioner_errors(self):
        """
        get dictionary of positioner errors for each stage
        """
        out = OrderedDict()
        for stage in self.stages:
            if stage in ('', None): continue
            err, stat = self._xps.PositionerErrorGet(self._sid, stage)
            err, val = self._xps.PositionerErrorStringGet(self._sid, stat)
            if len(val) < 1:
                val = 'OK'
            out[stage] = val
        return out

    def set_velocity(self, stage, velo, accl=None,
                    min_jerktime=None, max_jerktime=None):
        """
        set velocity for stage
        """
        if self._sid is None:
            self.connect()
        if stage not in self.stages:
            print("Stage '%s' not found" % stage)
            return
        ret, v_cur, a_cur, jt0_cur, jt1_cur = \
             self._xps.PositionerSGammaParametersGet(self._sid, stage)
        if accl is None:
            accl = a_cur
        if min_jerktime is None:
            min_jerktime = jt0_cur
        if max_jerktime is None:
            max_jerktime = jt1_cur
        self._xps.PositionerSGammaParametersGet(self._sid, stage, vel, accl,
                                                min_jerktime, max_jerktime)


    def move_group(self, group=None, **kws):
        """move group to supplied position
        """
        if group is None or group not in self.groups:
            group = self.traj_group
        if group is None:
            print("Do have a group to move")
            return
        posnames = [p.lower() for p in self.groups[group]['positioners']]
        ret = self._xps.GroupPositionCurrentGet(self._sid, group, len(posnames))
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

        self._xps.GroupMoveAbsolute(self._sid, group, vals)

    def move_stage(self, stage, value, relative=False):
        """
        move stage to position, optionally relative

        Parameters:
           stage (string): name of stage -- must be in self.stages
           value (float): target position
           relative (bool): whether move is relative [False]
        """
        if stage not in self.stages:
            print("Stage '%s' not found" % stage)
            return

        move = self._xps.GroupMoveAbsolute
        if relative:
            move = self._xps.GroupMoveRelative

        err, ret = move(self._sid, stage, [value])
        return ret

    def read_stage_position(self, stage):
        """
        return current stage position

        Parameters:
           stage (string): name of stage -- must be in self.stages
        """
        if stage not in self.stages:
            print("Stage '%s' not found0" % stage)
            return

        err, val = self._xps.GroupPositionCurrentGet(self._sid, stage, 1)
        return val


    def reboot(self, reconnect=True, timeout=120.0):
        """
        reboot XPS, optionally waiting to reconnect

        Parameters:
            reconnect (bool): whether to wait for reconnection [True]
            timeout (float): how long to wait before giving up, in seconds [60]
        """
        self.ftp_disconnect()
        self._xps.CloseAllOtherSockets(self._sid)
        self._xps.Reboot(self._sid)
        self._sid = -1
        self.groups = self.stages = self.stagetypes = None
        time.sleep(5.0)
        if reconnect:
            maxtime = time.time() + timeout
            while self._sid < 0:
                time.sleep(5.0)
                try:
                    self._sid = self._xps.TCP_ConnectToServer(self.host,
                                                              self.port,
                                                              self.timeout)
                except:
                    print("Connection Failed ", time.ctime(), sys.exc_info())

                if time.time() > maxtime:
                    break
            if self._sid >=0:
                self.connect()
            else:
                print("Could not reconnect to XPS.")


    def define_line_trajectories(self, axis, group=None,
                                 start=0, stop=1, step=0.001, scantime=10.0,
                                 accel=None, upload=True):
        """defines 'forward' and 'backward' trajectories for a simple
        single element line scan in PVT Mode
        """
        if group is not None:
            self.set_trajectory_group(group)

        if self.traj_group is None:
            print("Must define a trajectory group first!")
            return

        axis =  axis.upper()
        stage = "%s.%s" % (self.traj_group, axis)

        max_velo = self.stages[stage]['max_velo']
        max_accel = self.stages[stage]['max_accel']
        if accel is None:
            accel = max_accel
        accel = min(accel, max_accel)

        dist = (stop - start)*1.0
        sign = dist/abs(dist)
        scantime = abs(scantime)
        pixeltime = scantime * step / abs(dist)
        velo      = min(dist / scantime, max_velo)

        ramptime = abs(velo / accel)
        ramp     = 0.5 * velo * ramptime

        fore_traj = {'scantime':scantime,
                     'axes': [axis],
                     'accel': accel,
                     'nsegments': 3,
                     'ramptime': ramptime,
                     'pixeltime': pixeltime}

        this = {'start': start, 'stop': stop, 'step': step,
                'velo': velo, 'ramp': ramp, 'dist': dist}
        for attr in this.keys():
            for ax in self.traj_positioners:
                if ax == axis:
                    fore_traj["%s%s" % (ax, attr)] = this[attr]
                else:
                    fore_traj["%s%s" % (ax, attr)] = 0.0

        back_traj = fore_traj.copy()
        back_traj["%sstart" % axis] = fore_traj["%sstop" % axis]
        back_traj["%sstp" % axis]   = fore_traj["%sstart" % axis]
        for attr in ('velo', 'ramp', 'dist'):
            back_traj["%s%s" % (axis, attr)] *= -1.0

        self.trajectories['backward'] = back_traj
        self.trajectories['foreward'] = fore_traj

        # template for linear trajectory file:
        trajline1 = ['%(ramptime)f']
        trajline2 = ['%(scantime)f']
        trajline3 = ['%(ramptime)f']
        for p in self.traj_positioners:
            trajline1.append('%%(%sramp)f' % p)
            trajline1.append('%%(%svelo)f' % p)
            trajline2.append('%%(%sdist)f' % p)
            trajline2.append('%%(%svelo)f' % p)
            trajline3.append('%%(%sramp)f' % p)
            trajline3.append('%8.6f' % 0.0)
        trajline1 = (', '.join(trajline1)).strip()
        trajline2 = (', '.join(trajline2)).strip()
        trajline3 = (', '.join(trajline3)).strip()
        template = '\n'.join(['', trajline1, trajline2, trajline3])


        ret = True
        if upload:
            ret = False
            try:
                self.upload_trajectory('foreward.trj', template % fore_traj)
                self.upload_trajectory('backward.trj', template % back_traj)
                ret = True
            except:
                raise ValueError("error uploading trajectory")
        return ret


    def arm_trajectory(self, name):
        """
        set up the trajectory from previously defined, uploaded trajectory

        """
        if self.traj_group is None:
            print("Must set group name!")
        traj = self.trajectories.get(name, None)
        if traj is None:
            print("Cannot find trajectory named '%s'" %  name)
            return

        self.traj_file = '%s.trj'  % name
        axes  = traj['axes']
        ptime = traj['pixeltime']
        nsegs = traj['nsegments']

        ramps = [-traj['%sramp' % p] for p in self.traj_positioners]
        self.traj_state = ARMING

        kws = {}
        for ax in axes:
            kw[ax] = float(traj['%sstart' % ax] - traj['%sramp' % ax])}
        self.move_group(self.traj_group, **kws)

        g_output = []
        g_titles = []
        for out in self.gather_outputs:
            for ax in axes:
                g_output.append('%s.%s.%s' % (self.traj_group, ax, out))
                g_titles.append('%s.%s' % (ax, out))

        self.gather_titles = "%s\n#%s\n" % (self.gather_header, " ".join(g_titles))

        self._xps.GatheringReset(self._sid)
        self._xps.GatheringConfigurationSet(self._sid, self.gather_outputs)

        self._xps.MultipleAxesPVTPulseOutputSet(self._sid, self.traj_group,
                                                2, nsegs, ptime)

        self._xps.MultipleAxesPVTVerification(self._sid,
                                              self.traj_group,
                                              self.traj_file)

        self.traj_state = ARMED

    def run_trajectory(self, save=True, output_file='Gather.dat', verbose=False):

        """run a trajectory in PVT mode

        The trajectory *must be in the ARMED state
        """

        if self.traj_state != ARMED:
            raise XPSError("Must arm trajectory before running!")

        buffer = ('Always', '%s.PVT.TrajectoryPulse' % self.traj_group,)
        ret = self._xps.EventExtendedConfigurationTriggerSet(self._sid, buffer,
                                                          ('0','0'), ('0','0'),
                                                          ('0','0'), ('0','0'))

        ret = self._xps.EventExtendedConfigurationActionSet(self._sid,
                                                            ('GatheringOneData',),
                                                            ('',), ('',),('',),('',))

        eventID, m = self._xps.EventExtendedStart(self._sid)
        self.traj_state = RUNNING

        ret = self._xps.MultipleAxesPVTExecution(self._sid,
                                                 self.traj_group,
                                                 self.traj_file, 1)

        ret = self._xps.EventExtendedRemove(self._sid, eventID)
        ret = self._xps.GatheringStop(self._sid)

        self.traj_state = COMPLETE
        npulses = 0
        if save:
            npulses, buff = self.read_gathering()
            self.traj_state = WRITING
            self.save_gathering_file(output_file, buff, verbose=verbose)
        self.traj_state = IDLE
        return npulses


    def read_gathering(self):
        """
        read gathering data from XPS
        """
        self.traj_state = READING
        ret, npulses, nx = self._xps.GatheringCurrentNumberGet(self._sid)
        counter = 0
        while npulses < 1 and counter < 5:
            counter += 1
            time.sleep(0.5)
            ret, npulses, nx = self._xps.GatheringCurrentNumberGet(self._sid)
            print( 'Had to do repeat XPS Gathering: ', ret, npulses, nx)

        ret, buff = self._xps.GatheringDataMultipleLinesGet(self._sid, 0, npulses)

        if ret < 0:  # gathering too long: need to read in chunks
            nchunks = 3
            nx  = int((npulses-2) / nchunks)
            ret = 1
            while True:
                time.sleep(0.1)
                ret, xbuff = self._xps.GatheringDataMultipleLinesGet(self._sid, 0, nx)
                if ret == 0:
                    break
                nchunks = nchunks + 2
                nx      = int((npulses-2) / nchunks)
                if nchunks > 10:
                    print('looks like something is wrong with the XPS!')
                    break
            buff = [xbuff]
            for i in range(1, nchunks):
                ret, xbuff = self._xps.GatheringDataMultipleLinesGet(self._sid, i*nx, nx)
                buff.append(xbuff)
            ret, xbuff = self._xps.GatheringDataMultipleLinesGet(self._sid, nchunks*nx,
                                                                npulses-nchunks*nx)
            buff.append(xbuff)
            buff = ''.join(buff)

        obuff = buff[:]
        for x in ';\r\t':
            obuff = obuff.replace(x,' ')
        return npulses, obuff

    def save_gathering_file(self, fname, buffer, verbose=False):
        """save gathering buffer read from read_gathering() to text file"""
        f = open(fname, 'w')
        f.write(self.gather_titles)
        f.write(buffer)
        f.close()
        nlines = len(buffer.split('\n')) - 1
        if verbose:
            print('Wrote %i lines, %i bytes to %s' % (nlines, len(buff), fname))


if __name__ == '__main__':
    x = NewportXPS('164.54.160.180')
    x.read_systemini()
    print 'Groups: '
    for key, val in x.groups.items():
        print '  %s: %s' % (key, val)
    print 'Stages: '
    for key, val in x.stages.items():
        print key, val

    # x.save_systemini()
    #  x.save_stagesini()
