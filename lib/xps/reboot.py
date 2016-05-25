import time
import ftplib
from cStringIO import StringIO
from XPS_C8_drivers import  XPS

from .config import config


xps = XPS()
socketID = xps.TCP_ConnectToServer(config.host, config.port, config.timeout)
xps.Login(socketID, config.user, config.passwd)
#
# print socketID
#
xps.CloseAllOtherSockets(socketID)

print 'Rebooting XPS....'
xps.Reboot(socketID)

time.sleep(2.0)

xps = XPS()
socketID = xps.TCP_ConnectToServer(config.host, config.port, config.timeout)
xps.Login(socketID, config.user, config.passwd)

print 'Reconnected with socketID = ', socketID

time.sleep(3.0)
groupNames = ('FINE', 'THETA', 'COARSEX', 'COARSEY', 'COARSEZ', 'DETX')
actions =  ('GroupInitialize', 'GroupHomeSearch', 'GroupStatusGet')

for group in groupNames:
    print '== GROUP:: ' , group
    for action in actions:
        meth = getattr(xps, action)
        err, msg = meth(socketID, group)
        time.sleep(1.0)
        if err < 0:
            err, msg = meth(socketID, group)
            time.sleep(1.0)

        if err < 0:
            print "Group %s has status %s " % (group, msg)


#     for action in actions:
#         print action, group
#         stat, message = getattr(xps, action)(socketID, group)
#         print '    -> ', stat
#         time.sleep(2.0)
# ;
