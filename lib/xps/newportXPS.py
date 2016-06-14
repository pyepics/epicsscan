import time
import ftplib
import socket

from cStringIO import StringIO
from ConfigParser import  ConfigParser

from XPS_C8_drivers import XPS

from collections import OrderedDict
class def_config:
    port = 5001
    timeout = 10
    user = 'Administrator'
    passwd = 'Administrator'

class NewportXPS:
    def __init__(self, host, port=None, user=None,
                 passwd=None, timeout=None):
        self._xps = XPS()
        if port is None:
            port    = def_config.port
        if user is None:
            user    = def_config.user
        if passwd is None:
            passwd  = def_config.passwd
        if timeout is None:
            timeout = def_config.timeout

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
        self._sid = None
        self.ftpconn = None
        self.ftphome = '/Admin'
        self.connect()

    def status_report(self):
        """return printable status report"""
        out = ["# Newport XPS  %s  (%s)" % (self.host, socket.getfqdn(self.host)),
               "# %s " % time.ctime()]
        out.append("############################")
        hstat = self.get_hardware_status()
        perrs = self.get_positioner_errors()

        for groupname, status in self.get_group_status().items():
            out.append("Group: %s, Status: %s " % (groupname, status))
            for stagename in self.groups[groupname]:
                istage = self.stages.index(stagename)
                driver = self.stagetypes[istage]
                out.append("   Stage: %s, Driver: %s"  % (stagename, driver))
                out.append("      Hardware Status: %s"  % (hstat[stagename]))
                out.append("      Positioner Errors: %s"  % (perrs[stagename]))

        out.append("############################")
        return "\n".join(out)



    def connect(self):
        self._sid = self._xps.TCP_ConnectToServer(self.host,
                                                  self.port, self.timeout)
        try:
            self._xps.Login(self._sid, self.user, self.passwd)
        except:
            raise ValueError, 'Login failed for %s' % self.host
        try:
            ftpconn = ftplib.FTP()
            ftpconn.connect(self.host)
            ftpconn.login(self.user, self.passwd)
        except:
            raise ValueError, 'FTP Login failed for %s' % self.host
        err, val = self._xps.FirmwareVersionGet(self._sid)
        self.firmware_version = val
        if 'Q8' in self.firmware_version:
            self.ftphome = ''

        self.ftpconn = ftpconn
        self.read_systemini()


    def read_systemini(self):
        if self.ftpconn is None:
            return
        self.ftpconn.cwd('%s/Config' % self.ftphome)
        output = []
        x = self.ftpconn.retrbinary('RETR system.ini', output.append)
        self.sysconf = ''.join(output)

        sconf = ConfigParser()
        sconf.readfp(StringIO(self.sysconf))
        groups = OrderedDict()

        stages = [None]*8
        stagetypes = [None]*8

        for sect in sconf.sections():
            if 'plugnumber' in sconf.options(sect):
                index = sconf.getint(sect, 'plugnumber')
                stages[index-1] = sect
                stagetypes[index-1] = sconf.get(sect, 'stagename')

            elif 'positionerinuse' in  sconf.options(sect):
                val = sconf.get(sect, 'positionerinuse')
                groups[sect] = ["%s.%s" % (sect, p.strip()) for p in val.split(',')]

        self.groups = groups
        self.stages = stages
        self.stagetypes = stagetypes

    def save_systemini(self, fname='system.ini'):
        """save system.ini to disk

        Parameters:
           fname  (string): name of file to save to ['system.ini']
        """
        if self.ftpconn is None:
            return
        self.ftpconn.cwd('%s/Config' % self.ftphome)
        output = []
        x = self.ftpconn.retrbinary('RETR system.ini', output.append)
        fout = open(fname, 'w')
        fout.write(''.join(output))
        fout.close()


    def save_stagesini(self, fname='stages.ini'):
        """save stages.ini to disk

        Parameters:
           fname  (string): name of file to save to ['stages.ini']
        """
        if self.ftpconn is None:
            return
        self.ftpconn.cwd('%s/Config' % self.ftphome)
        output = []
        x = self.ftpconn.retrbinary('RETR stages.ini', output.append)
        fout = open(fname, 'w')
        fout.write(''.join(output))
        fout.close()


    def initialize_groups(self, with_encoder=True, home=False):
        """
        initialize groups, optionally homing each.

        Parameters:
            with_encoder (bool): whethter to initialize with encoder [True]
            home (bool): whether to home all groups [False]
        """
        if self._sid is None:
            self.connect()

        GroupInit = self._xps.GroupInitialize
        if with_encoder:
            GroupInit = self._xps.GroupInitializeWithEncoderCalibration
        for group in self.groups:
            err, ret = GroupInit(self._sid, group)
            if err is not 0:
                print("error initializing group '%s', %i" % (group, ret))
            time.sleep(0.25)

        if home:
            for group in self.groups:
                self.home_group(group)

    def home_group(self, group=None):
        """
        home group

        Parameters:
            group (None or string): name of group to home [None]

        Notes:
            if group is `None`, all groups will be homed.
        """
        if self._sid is None:
            self.connect()
        if group is None:
            for group in self.groups:
                err, ret = self._xps.GroupHomeSearch(self._sid, group)
                if err is not 0:
                    print("error homing group '%s', %s" % (group, ret))
                time.sleep(0.25)
        elif group in self.groups:
            err, ret = self._xps.GroupHomeSearch(self._sid, group)
            if err is not 0:
                print("error homing group '%s', %s" % (group, ret))
        else:
            print("Group '%s' not found" % group)

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


    def move(self, stage, value, relative=False):
        """
        move stage to position, optionally relative

        Parameters:
           stage (string): name of stage -- must be in self.stages
           value (float): target position
           relative (bool): whether move is relative [False]
        """
        if stage not in self.stages:
            print("Stage '%s' not found")
            return

        move = self._xps.GroupMoveAbsolute
        if relative:
            move = self._xps.GroupMoveRelative

        err, ret = move(self._sid, stage, [value])
        return ret

    def read_position(self, stage):
        """
        return current stage position

        Parameters:
           stage (string): name of stage -- must be in self.stages
        """
        if stage not in self.stages:
            print("Stage '%s' not found")
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
        self.ftpconn.close()
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
                print("Could notreconnect to XPS.")

if __name__ == '__main__':
    x = NewportXPS('164.54.160.180')
    print 'Groups: '
    for key, val in x.groups.items():
        print '  %s: %s' % (key, val)
    print 'Stages: '
    for i, name in enumerate(x.stages):
        print i, name, x.stagetypes[i]

    x.save_systemini()
    x.save_stagesini()
