from __future__ import print_function
import time
import ftplib
import socket

from six.moves import StringIO
from six.moves.configparser import  ConfigParser

from .XPS_C8_drivers import XPS

from collections import OrderedDict

from ..debugtime import debugtime

class XPSError(Exception):
    """XPS Controller Exception"""
    def __init__(self, msg,*args):
        self.msg = msg
    def __str__(self):
        return str(self.msg)

IDLE, ARMING, ARMED, RUNNING, COMPLETE, WRITING, READING = \
      'IDLE', 'ARMING', 'ARMED', 'RUNNING', 'COMPLETE', 'WRITING', 'READING'


def withConnectedXPS(fcn):
    """decorator to ensure a NewportXPS is connected before a method is called"""
    def wrapper(self, *args, **kwargs):
        if self._sid is None or len(self.groups) < 1 or len(self.stages) < 1:
            self.connect()
        return fcn(self, *args, **kwargs)
    wrapper.__doc__ = fcn.__doc__
    wrapper.__name__ = fcn.__name__
    wrapper.__dict__.update(fcn.__dict__)

    return wrapper

class NewportXPS:
    gather_header = '# XPS Gathering Data\n#--------------'
    def __init__(self, host, group=None,
                 username='Administrator', password='Administrator',
                 port=5001, timeout=10, extra_triggers=0,
                 outputs=('CurrentPosition', 'SetpointPosition')):

        socket.setdefaulttimeout(5.0)
        try:
            host = socket.gethostbyname(host)
        except:
            raise ValueError('Could not resolve XPS name %s' % host)
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.extra_triggers = extra_triggers

        self.errcodes = OrderedDict()
        self.gather_outputs = tuple(outputs)
        self.trajectories = {}
        self.traj_state = IDLE
        self.traj_group = None
        self.traj_file = None
        self.traj_positioners = None

        self.stages = OrderedDict()
        self.groups = OrderedDict()

        self.ftpconn = ftplib.FTP()
        self._sid = None
        self._xps = XPS()
        self.connect()
        if group is not None:
            self.set_trajectory_group(group)

    @withConnectedXPS
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
            out.append("%s (%s), Status: %s" %
                       (groupname, this['category'], status))
            for pos in this['positioners']:
                stagename = '%s.%s' % (groupname, pos)
                stage = self.stages[stagename]
                out.append("   %s (%s)"  % (stagename, stage['type']))
                out.append("      Hardware Status: %s"  % (hstat[stagename]))
                out.append("      Positioner Errors: %s"  % (perrs[stagename]))
        return "\n".join(out)

    def ftp_connect(self):
        """open ftp connection"""
        self.ftpconn.connect(self.host)
        self.ftpconn.login(self.username, self.password)

    def ftp_disconnect(self):
        "close ftp connnection"
        self.ftpconn.close()

    def connect(self):
        self._sid = self._xps.TCP_ConnectToServer(self.host,
                                                  self.port, self.timeout)
        try:
            self._xps.Login(self._sid, self.username, self.password)
        except:
            raise XPSError('Login failed for %s' % self.host)

        err, val = self._xps.FirmwareVersionGet(self._sid)
        self.firmware_version = val

        if 'Q8' in self.firmware_version:
            self.ftphome = ''
        else:
            self.ftphome = '/Admin'

        try:
            self.read_systemini()
        except:
            print("Could not read system.ini")

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
        """read group info from system.ini
        this is part of the connection process
        """
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
            if line.startswith('#'):
                continue

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
                        groups[p]['category'] = cat.strip()
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

    @withConnectedXPS
    def set_trajectory_group(self, group, reenable=False):
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

        if reenable:
            try:
                self.disable_group(self.traj_group)
            except XPSError:
                pass

            time.sleep(0.1)
            try:
                self.enable_group(self.traj_group)
            except XPSError:
                print("Warning: could not enable trajectory group '%s'"% self.traj_group)
                return

        for i in range(64):
            self._xps.EventExtendedRemove(self._sid, i)

        # build template for linear trajectory file:
        trajline1 = ['%(ramptime)f']
        trajline2 = ['%(scantime)f']
        trajline3 = ['%(ramptime)f']
        for p in self.traj_positioners:
            trajline1.append('%%(%s_ramp)f' % p)
            trajline1.append('%%(%s_velo)f' % p)
            trajline2.append('%%(%s_dist)f' % p)
            trajline2.append('%%(%s_velo)f' % p)
            trajline3.append('%%(%s_ramp)f' % p)
            trajline3.append('%8.6f' % 0.0)
        trajline1 = (', '.join(trajline1)).strip()
        trajline2 = (', '.join(trajline2)).strip()
        trajline3 = (', '.join(trajline3)).strip()
        self.linear_template = '\n'.join(['', trajline1, trajline2, trajline3])


    @withConnectedXPS
    def _group_act(self, method, group=None, action='doing something with'):
        """wrapper for many group actions"""
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

    def kill_group(self, group=None):
        """
        initialize groups, optionally homing each.

        Parameters:
            with_encoder (bool): whethter to initialize with encoder [True]
            home (bool): whether to home all groups [False]
        """

        method = 'GroupKill'
        self._group_act(method, group=group, action='killing')

    def initialize_allgroups(self, with_encoder=True, home=False):
        """
        initialize all groups, no homing
        """
        for g in self.groups:
            self.initialize_group(group=g)

    def home_allgroups(self, with_encoder=True, home=False):
        """
        home all groups
        """
        for g in self.groups:
            self.home_group(group=g)


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

    @withConnectedXPS
    def get_group_status(self):
        """
        get dictionary of status for each group
        """
        out = OrderedDict()
        for group in self.groups:
            err, stat = self._xps.GroupStatusGet(self._sid, group)
            e1, val = self._xps.GroupStatusStringGet(self._sid, stat)
            print("GROUP ", group, err, stat, e1, val)
            out[group] = val
        return out

    @withConnectedXPS
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

    @withConnectedXPS
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

    @withConnectedXPS
    def set_velocity(self, stage, velo, accl=None,
                    min_jerktime=None, max_jerktime=None):
        """
        set velocity for stage
        """
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

    @withConnectedXPS
    def abort_group(self, group=None):
        """abort group move"""
        if group is None or group not in self.groups:
            group = self.traj_group
        if group is None:
            print("Do have a group to move")
            return
        ret = self._xps.GroupMoveAbort(self._sid, group)

    @withConnectedXPS
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

    @withConnectedXPS
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

    @withConnectedXPS
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

    @withConnectedXPS
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


    @withConnectedXPS
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

        max_velo  = 0.95*self.stages[stage]['max_velo']
        max_accel = 0.95*self.stages[stage]['max_accel']
        if accel is None:
            accel = max_accel
        accel = min(accel, max_accel)

        scandir  = 1.0
        if start > stop:
            scandir = -1.0
        step = scandir*abs(step)

        npulses = 1 + int((abs(stop - start) + abs(step)*0.1) / abs(step))
        scantime = float(abs(scantime))
        pixeltime= scantime / (npulses-1)

        scantime = pixeltime*npulses
        distance = (abs(stop - start) + abs(step))*1.0
        velocity = min(distance/scantime, max_velo)
        ramptime = 1.5 * abs(velocity/accel)
        rampdist = velocity * ramptime * scandir


        self.trajectories['foreward'] = {'axes': [axis],
                                         'start': [start-step/2.0-rampdist],
                                         'stop':  [stop+step/2.0+rampdist],
                                         'pixeltime': pixeltime,
                                         'npulses': npulses,
                                         'nsegments': 3}

        self.trajectories['backward'] = {'axes':  [axis],
                                         'start': [stop+step/2.0+rampdist],
                                         'stop':  [start-step/2.0-rampdist],
                                         'pixeltime': pixeltime,
                                         'npulses': npulses,
                                         'nsegments': 3}

        base = {'start': start, 'stop': stop, 'step': step,
                'velo': velocity, 'ramp': rampdist, 'dist': distance}
        fore = {'ramptime': ramptime, 'scantime': scantime}
        for attr in base:
            for ax in self.traj_positioners:
                val = 0.0
                if ax == axis:
                    val = base[attr]
                fore["%s_%s" % (ax, attr)] = val

        back = fore.copy()
        back["%s_start" % axis] = fore["%s_stop" % axis]
        back["%s_stop" % axis]  = fore["%s_start" % axis]
        for attr in ('velo', 'ramp', 'dist'):
            back["%s_%s" % (axis, attr)] *= -1.0

        # print("TRAJ Text Fore:")
        # print(self.linear_template % fore)
        # print("TRAJ Text Back:")
        # print(self.linear_template % back)

        ret = True
        if upload:
            ret = False
            try:
                self.upload_trajectory('foreward.trj',
                                       self.linear_template % fore)
                self.upload_trajectory('backward.trj',
                                       self.linear_template % back)
                ret = True
            except:
                raise ValueError("error uploading trajectory")
        return ret

    @withConnectedXPS
    def arm_trajectory(self, name):
        """
        set up the trajectory from previously defined, uploaded trajectory
        """
        if self.traj_group is None:
            print("Must set group name!")

        traj = self.trajectories.get(name, None)

        if traj is None:
            raise XPSError("Cannot find trajectory named '%s'" %  name)

        self.traj_state = ARMING
        self.traj_file = '%s.trj'  % name

        # move_kws = {}
        outputs = []
        for out in self.gather_outputs:
            for i, ax in enumerate(traj['axes']):
                outputs.append('%s.%s.%s' % (self.traj_group, ax, out))
                # move_kws[ax] = float(traj['start'][i])


        end_segment = traj['nsegments'] - 1 + self.extra_triggers
        # self.move_group(self.traj_group, **move_kws)
        self.gather_titles = "%s\n#%s\n" % (self.gather_header, " ".join(outputs))
        self._xps.GatheringReset(self._sid)
        self._xps.GatheringConfigurationSet(self._sid, outputs)
        self._xps.MultipleAxesPVTPulseOutputSet(self._sid, self.traj_group,
                                                2, end_segment,
                                                traj['pixeltime'])

        self._xps.MultipleAxesPVTVerification(self._sid, self.traj_group, name)
        self.traj_state = ARMED

    @withConnectedXPS
    def run_trajectory(self, name=None, save=True,
                       output_file='Gather.dat', verbose=False):

        """run a trajectory in PVT mode

        The trajectory *must be in the ARMED state
        """

        if name in self.trajectories:
            self.arm_trajectory(name)

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
            self.read_and_save(output_file)
        self.traj_state = IDLE
        return npulses

    @withConnectedXPS
    def read_and_save(self, output_file):
        "read and save gathering file"
        self.ngathered = 0
        npulses, buff = self.read_gathering(set_idle_when_done=False)
        self.save_gathering_file(output_file, buff,
                                 verbose=False,
                                 set_idle_when_done=False)
        self.ngathered = npulses

    @withConnectedXPS
    def read_gathering(self, set_idle_when_done=True, debug=False):
        """
        read gathering data from XPS
        """
        dt = debugtime()
        self.traj_state = READING
        ret, npulses, nx = self._xps.GatheringCurrentNumberGet(self._sid)
        counter = 0
        while npulses < 1 and counter < 5:
            counter += 1
            time.sleep(0.5)
            ret, npulses, nx = self._xps.GatheringCurrentNumberGet(self._sid)
            print( 'Had to do repeat XPS Gathering: ', ret, npulses, nx)
        # dt.add('CurrentNumber %i/%i/%i/%i' %(ret, npulses, nx, counter))
        ret, buff = self._xps.GatheringDataMultipleLinesGet(self._sid, 0, npulses)
        # dt.add('DataMultipleLinesGet:  %i, %i '%(ret, len(buff)))
        nchunks = -1
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

        # dt.add('MultipleLinesGet nchunks=%i' %(nchunks))
        obuff = buff[:]
        for x in ';\r\t':
            obuff = obuff.replace(x,' ')
        # dt.add(' buffer cleaned')
        if set_idle_when_done:
            self.traj_state = IDLE
        if debug:
            dt.show()
        return npulses, obuff

    def save_gathering_file(self, fname, buffer, verbose=False, set_idle_when_done=True):
        """save gathering buffer read from read_gathering() to text file"""
        self.traj_state = WRITING
        f = open(fname, 'w')
        f.write(self.gather_titles)
        f.write(buffer)
        f.close()
        nlines = len(buffer.split('\n')) - 1
        if verbose:
            print('Wrote %i lines, %i bytes to %s' % (nlines, len(buff), fname))
        if set_idle_when_done:
            self.traj_state = IDLE

if __name__ == '__main__':
    x = NewportXPS('164.54.160.180')
    x.read_systemini()
    print(x.status_report())
