#
# Gen2 observation display server
#
"""
Gen2 observation display server

Usage (e.g):
$ g2disp_server.py --loglevel=20 --log=$HOME/gen2/logs/g2disp_server.log
"""
import sys
import time
import os
import glob
import logging
import threading

from ginga.util.paths import ginga_home

from g2base import ssdlog
from g2base.remoteObjects import remoteObjects as ro

from g2remote.g2connect import G2Connect

# where the different configuration files are stored
default_cfgdir = os.path.join(ginga_home, 'sites')
# default interface to connect to me (override with --host)
default_host = 'localhost'
# default port to connect to me (override with --port)
default_port = 23901
# default authorization to prevent accidental remoteObjects connections
# (not meant as a security mechanism)
default_auth = "g2disp_server:g2disp_server"


class g2Disp_Server:

    def __init__(self, cfg_dir, logger):

        self.logger = logger

        self.g2conn = G2Connect(logger=logger)
        self.cfg_dir = cfg_dir
        self.configs = dict()
        self.site_names = []

    def read_configs(self):
        """Read/Update the configurations."""
        self.disconnect()

        self.configs = dict()
        for path in glob.glob(os.path.join(self.cfg_dir, '*.toml')):
            _, fname = os.path.split(path)
            cname, _ = os.path.splitext(fname)
            name = self.g2conn.rdconfig(path)
            if name is None:
                name = cname
            self.configs[name] = path

        self.site_names = list(self.configs.keys())
        if len(self.site_names) == 0:
            self.logger.error("No configs found!")

    def get_sites(self):
        """Return list of configuration names we know about."""
        return self.site_names

    def connect(self, name):
        """Connect for configuration `name`."""
        # just in case we are already connected...
        self.disconnect()

        self.logger.info(f"attempting to connect to site '{name}'")
        try:
            conf_file = self.configs[name]
            self.g2conn.rdconfig(conf_file)

            self.g2conn.connect()

            config = self.g2conn.config.copy()
            config['ssh_key'] = '-- N/A --'
            return config

        except Exception as e:
            errmsg = f"error connecting via '{name}': {e}"
            self.logger.error(errmsg, exc_info=True)
            raise Exception(errmsg)

    def disconnect(self):
        """Disconnect any current connection."""
        self.logger.info("attempting disconnection to current site")
        try:
            self.g2conn.disconnect()
            return ro.OK

        except Exception as e:
            self.logger.error("error disconnecting: {e}")
            return ro.ERROR

    # callback to quit the program
    def quit(self):
        self.logger.info('quit service...')
        self.disconnect()


def main(options, args):
    ev_quit = threading.Event()
    logger = ssdlog.make_logger('g2disp_server', options)

    service = g2Disp_Server(options.config_dir, logger)
    logger.info("reading configuration files ...")
    service.read_configs()

    hosts = options.rohosts.split(',')
    try:
        ro.init(hosts)

    except ro.remoteObjectError as e:
        logger.error("Error initializing remote objects subsystem: %s" % \
                     str(e))
        sys.exit(1)

    myhost = ro.get_myhost(short=True)
    svcname = f'g2disp_service_{myhost}'
    server = ro.remoteObjectServer(svcname=svcname,
                                   obj=service, logger=logger,
                                   host=options.host, port=options.port,
                                   numthreads=4, threaded_server=True,
                                   usethread=False, ns=False,
                                   ev_quit=ev_quit, default_auth=False,
                                   authDict=dict([default_auth.split(':')]),
                                   method_list=['connect', 'disconnect',
                                                'get_sites', 'quit',
                                                'read_configs'])
    while not ev_quit.is_set():
        try:
            server.ro_start(wait=True)

        except KeyboardInterrupt:
            logger.error("Received keyboard interrupt!")
            ev_quit.set()

        except Exception as e:
            logger.error(f"error in server: {e}", exc_info=True)
            time.sleep(5)

    service.disconnect()
    #ev_quit.set()
    logger.info("exiting server...")
