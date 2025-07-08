# Epics Scanning with PyEpics and Postgres


.. image:: https://zenodo.org/badge/4185/pyepics/stepscan.png
   :target: http://dx.doi.org/10.5281/zenodo.10092

Scannng and data acquisition with pyepics using a postgresql database
for configuration and communication of scanning commands and status.

Classes and Functions for simple step scanning for epics.

This does not used the Epics SScan Record, and the scan is intended to run
as a python application, but many concepts from the Epics SScan Record are
borrowed.  Where appropriate, the difference will be noted here.
