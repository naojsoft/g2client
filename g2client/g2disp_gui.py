#
# Gen2 observation workstation client -- GUI version
#
"""
Gen2 observation workstation client -- GUI version
"""
import sys, time
import re, os
import glob
import logging
import threading
import queue as Queue

from ginga.gw import Widgets, Viewers, GwHelp
from ginga.RGBImage import RGBImage
from ginga.misc import Settings
from ginga.util.paths import ginga_home

from g2base import Bunch, ssdlog
from g2base.remoteObjects import remoteObjects as ro
from g2remote.g2connect import G2Connect

from g2client import icons
from g2client.g2disp_server import default_host, default_port, default_auth


# path to our icons
module_path = os.path.split(icons.__file__)[0]


class g2Disp_GUI:

    def __init__(self, options, logger, ev_quit):

        self.options = options
        self.logger = logger
        self.ev_quit = ev_quit

        self.w = Bunch.Bunch()
        self.name = None
        self.g2conn = G2Connect(logger=self.logger)

        # size (in lines) we will let log buffer grow to before
        # trimming
        self.logsize = 5000

        self.site_names = []
        self.proxy = None

    def connect_proxy(self):
        self.proxy = ro.remoteObjectClient(default_host, default_port,
                                           auth=default_auth)
        try:
            self.site_names = self.proxy.get_sites()
        except Exception as e:
            self.logger.error(f"Can't establish connection to proxy server: {e}", exc_info=True)
            self.site_names = []
        if len(self.site_names) > 0:
            self.name = self.site_names[0]

    def build_gui(self):
        self.app = Widgets.Application(logger=self.logger)
        self.top = self.app.make_window("Gen2 Display Server")
        self.top.add_callback('close', self.quit)

        vbox = Widgets.VBox()
        vbox.set_border_width(2)
        vbox.set_spacing(1)

        menubar = Widgets.Menubar()

        # create a File pulldown menu, and add it to the menu bar
        filemenu = menubar.add_name('File')

        reload = filemenu.add_name("Reload")
        reload.add_callback('activated', self.reload_cb)
        showlog = filemenu.add_name("Show Log")
        showlog.add_callback('activated', lambda w: self.showlog())

        w = filemenu.add_name("Mute", checkable=True)
        w.set_state(False)
        # functionality is TODO
        w.set_enabled(False)
        w.add_callback('activated', self.muteOnOff)

        filemenu.add_separator()

        quit_item = filemenu.add_name("Exit")
        quit_item.add_callback('activated', self.quit)

        vbox.add_widget(menubar, stretch=0)

        nb = Widgets.TabWidget()
        vbox.add_widget(nb, stretch=1)
        self.w.nb = nb

        fi = Viewers.CanvasView(logger=self.logger)
        fi.enable_autocuts('on')
        fi.set_autocut_params('histogram')
        fi.enable_auto_orient(True)
        fi.enable_autozoom('off')
        fi.scale_to(1, 1)
        fi.set_bg(0.2, 0.2, 0.2)
        self.viewer = fi

        fi.set_desired_size(350, 150)
        iw = Viewers.GingaViewerWidget(viewer=fi)
        vbox.add_widget(iw, stretch=1)

        #fi.ui_set_active(True)

        # load logo
        logo_path = os.path.join(module_path, "gen2_logo.png")
        logo = RGBImage(logger=self.logger)
        logo.load_file(logo_path)
        fi.set_image(logo)

        nb.add_widget(iw, "Top")

        vbox.add_widget(nb, stretch=1)

        # bottom buttons
        btnbox = Widgets.HBox()

        cbox = Widgets.ComboBox()
        for name in self.site_names:
            cbox.append_text(name)
        if len(self.site_names) > 0:
            cbox.set_index(0)
        cbox.add_callback('activated', self.select_system_cb)
        self.w.site_menu = cbox
        btnbox.add_widget(cbox, stretch=0)

        w = Widgets.Button('Connect')
        w.add_callback('activated', self.connect_cb)
        btnbox.add_widget(w, stretch=0)

        w = Widgets.Button('Disconnect')
        w.add_callback('activated', self.disconnect_cb)
        btnbox.add_widget(w, stretch=0)

        #btnbox.add_widget(Widgets.Label(''))

        vbox.add_widget(btnbox, stretch=0)

        # pop-up log file
        self.tmr_log = GwHelp.Timer(1.0)
        self.tmr_log.add_callback('expired', self.logupdate)
        self.create_logwindow()

        self.top.set_widget(vbox)
        self.top.show()

        if self.options.geometry:
            self.set_pos(self.options.geometry)


    def create_logwindow(self):
        # pop-up log file
        self.w.log = self.app.make_window("Application Log")
        self.w.log.add_callback('close', lambda w: self.closelog())

        vbox = Widgets.VBox()
        vbox.set_border_width(2)
        vbox.set_spacing(1)

        tw = Widgets.TextArea(wrap=False, editable=False)
        tw.set_limit(self.logsize)
        self.w.logtw = tw

        self.queue = Queue.Queue()
        guiHdlr = ssdlog.QueueHandler(self.queue)
        fmt = logging.Formatter(ssdlog.STD_FORMAT)
        guiHdlr.setFormatter(fmt)
        guiHdlr.setLevel(logging.INFO)
        self.logger.addHandler(guiHdlr)

        vbox.add_widget(tw, stretch=1)

        # bottom buttons
        btnbox = Widgets.HBox()

        cls = Widgets.Button("Close")
        cls.add_callback('activated', lambda w: self.closelog())
        btnbox.add_widget(cls)
        btnbox.add_widget(Widgets.Label(''), stretch=1)
        vbox.add_widget(btnbox)

        self.w.log.set_widget(vbox)
        tw.resize(800, 1000)

    def closelog(self):
        # close log window
        self.w.log.hide()
        return True

    def showlog(self):
        # open log window
        self.w.log.show()

    def muteOnOff(self, w, tf):
        # mute audio
        if tf:
            self.obj.muteOn()
        else:
            self.obj.muteOff()

    def select_system_cb(self, w, idx):
        self.name = w.get_text()

        self.all_viewers_off()
        return True

    def reload_cb(self, w):
        self.disconnect_cb(w)
        # re-establish server connection and reload manu
        self.connect_proxy()

        cbox = self.w.site_menu
        cbox.clear()
        for name in self.site_names:
            cbox.append_text(name)
        if len(self.site_names) > 0:
            cbox.set_index(0)
        return True

    def set_pos(self, geom):
        # TODO: currently does not seem to be honoring size request
        match = re.match(r'^(?P<size>\d+x\d+)?(?P<pos>[\-+]\d+[\-+]\d+)?$',
                         geom)
        if not match:
            return

        size = match.group('size')
        pos = match.group('pos')

        if size:
            match = re.match(r'^(\d+)x(\d+)$', size)
            if match:
                width, height = [int(i) for i in match.groups()]
                self.top.resize(width, height)

        # TODO: placement
        if pos:
            match = re.match(r'^([+\-]\d+)([+\-]\d+)$', pos)
            if match:
                x, y = [int(i) for i in match.groups()]
                self.top.move(x, y)


    def logupdate(self, tmr):
        # TODO: remove some of the old log stuff at the top of the buffer!
        try:
            while True:
                msgstr = self.queue.get(block=False)

                self.w.logtw.append_text(msgstr + '\n',
                                         autoscroll=True)

        except Queue.Empty:
            if not self.ev_quit.is_set():
                tmr.set(1.0)


    def connect_cb(self, w):
        if self.name is None:
            # TODO: pop up an error
            self.logger.error("No site selected!")
            return
        # just in case the user did something like close the viewers
        # without disconnecting...
        self.disconnect_cb(w)

        try:
            self.logger.info(f"trying to activate '{self.name}'")
            config = self.proxy.connect(self.name)
            self.g2conn.config = config

            self.all_viewers_on()

        except Exception as e:
            self.logger.error(f"error connecting: {e}", exc_info=True)

    def disconnect_cb(self, w):
        self.all_viewers_off()
        try:
            self.proxy.disconnect()

        except Exception as e:
            self.logger.error(f"error disconnecting: {e}")
            return

    def all_viewers_on(self):
        self.logger.info("showing screens")
        try:
            self.g2conn.start_all()

        except Exception as e:
            self.logger.error(f"error displaying screens: {e}",
                              exc_info=True)

    def all_viewers_off(self):
        self.logger.info("All viewers OFF")
        try:
            self.g2conn.stop_all()

        except Exception as e:
            self.logger.error(f"error stopping screens: {e}",
                              exc_info=True)

    def mute_on(self):
        # NOP, for now
        pass

    def mute_off(self):
        # NOP, for now
        pass

    # callback to quit the program
    def quit(self, *args):
        self.disconnect_cb(None)
        self.logger.debug('setting ev_quit')
        self.ev_quit.set()
        self.logger.debug('quitting app')
        self.app.quit()
        self.logger.debug('done quitting')


def main(options, args):
    ev_quit = threading.Event()
    logger = ssdlog.make_logger('g2disp_gui', options)

    g2disp = g2Disp_GUI(options, logger, ev_quit)
    g2disp.connect_proxy()

    g2disp.build_gui()

    g2disp.app.mainloop()
