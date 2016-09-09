from epics import caput
def abort_slewscan(mapper='13XRM:map:'):
    "kludgy way to force abort of slewscan"
    caput(mapper  + 'Abort', 1)

