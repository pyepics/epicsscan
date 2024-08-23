"""
Detector Trigger
"""
from time import time
from epics import get_pv, poll

from ..saveable import Saveable

class Trigger(Saveable):
    """
Detector Trigger for a scan. The interface is:
    trig = Trigger(pvname, value=1)
         defines a trigger PV and trigger value

    trig.start(value=None)
         starts the trigger (value will override value set on creation)

    trig.done       True if the start has completed.
    trig.runtime    time for last .start() to complete

Example usage:
    trig = Trigger(pvname)
    trig.start()
    while not trig.done:
        time.sleep(1.e-4)
    <read detector data>
    """
    def __init__(self, pvname, value=1, **kws):
        Saveable.__init__(self, pvname, value=value, **kws)
        self.pv = get_pv(pvname)
        self._val = value
        self.done = False
        self._t0 = 0
        self.runtime = -1

    def __repr__(self):
        return "trigger(%s, value=%i)" % (self.pv.pvname, self._val)

    def __onComplete(self, **kws):
        self.done = True
        self.runtime = time() - self._t0

    def start(self, value=1):
        """triggers detector"""
        self.done = False
        self.runtime = -1
        self._t0 = time()
        if value is None:
            value = self._val
        self.pv.put(value, callback=self.__onComplete)
        poll(0.001, 0.5)

    def abort(self, value=0, wait=False):
        """abort trigger"""
        self.pv.put(value, wait=wait)
