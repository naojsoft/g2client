#! /usr/bin/env python
#
from g2client.version import version
import os

srcdir = os.path.dirname(__file__)

try:
    from setuptools import setup

except ImportError:
    from distutils.core import setup

setup(
    name = "g2client",
    version = version,
    author = "Software Division, Subaru Telescope, NAOJ",
    author_email = "ocs@naoj.org",
    description = ("A client for observing with the Subaru Telescope Observation Control System."),
    license = "BSD",
    keywords = "subaru, telescope, observation, client",
    url = "http://naojsoft.github.com/g2client",
    packages = ['g2client',
                'g2client.util',
                'g2client.icons',
                ],
    package_data = {'g2client.icons':['*.png']},
    scripts = ['scripts/datasink', 'scripts/soundsink', 'scripts/g2disp',
               'scripts/g2disp_gui'],
    classifiers = [
        "License :: OSI Approved :: BSD License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX",
        "Topic :: Scientific/Engineering :: Astronomy",
    ],
)
