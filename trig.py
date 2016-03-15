from lib.detectors import Trigger, Xspress3Trigger
import time
import epics

trig = Xspress3Trigger('13QX4:')

for i in range(10):
    time.sleep(1.0)
    print('Run ' , i)
    trig.start()
    while not trig.done:
        time.sleep(0.001)
    print('done. %.2f' % (trig.runtime))

###
#
# from scan_credentials import conn
# # conn['debug'] = True
# t0 = time.time()
# db = ScanDB(**conn)
# print("DB Connect ", time.time()-t0)
# pvnames =  db.getall('pvs')
# pvlist = []
# print("PVlist ", len(pvnames), time.time()-t0)
# for p in pvnames:
#     pvlist.append(epics.get_pv(p.name))
#     # print p.name, p
#
# time.sleep(0.05)
# print("Epics connect ", time.time()-t0)
