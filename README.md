This is the g2client module, part of the Gen2 Observation Control
System.

It provides the client program for connecting observation workstations
to the Gen2 servers running the OCS.  This package is necessary for a
site to participate as a local or remote observation location.

## Dependencies

* Requires `g2cam` and `ginga` packages from naojsoft.

* For client use also requires the 'vncviewer` and `paplay` programs to
  be installed and in the PATH for connecting screens and playing
  sounds.  For VNC client we recommend tigervnc.

## Installation

It is recommended that you install a virtual (miniconda, virtualenv,
etc) environment to run the software in with related dependencies.

Activate this environment and then:

```bash
$ python setup.py install
```


