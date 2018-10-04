#
# Eric Jeschke (eric@naoj.org)
#
from __future__ import print_function

import sys, time
import re, os
import logging
import threading

from ginga.gw import Widgets, Viewers, GwHelp
from ginga.RGBImage import RGBImage
from ginga.util.six.moves import queue as Queue

from g2base import Bunch, ssdlog

from g2client import g2disp, icons
from g2client.util import Recorder


# path to our icons
module_path = os.path.split(icons.__file__)[0]


class g2Disp_GUI(object):

    def __init__(self, options, obj, ev_quit):

        self.options = options
        self.obj = obj
        # Share main object's logger
        self.logger = obj.logger
        self.w = Bunch.Bunch()

        self.ev_quit = ev_quit

        # size (in lines) we will let log buffer grow to before
        # trimming
        self.logsize = 5000
        self.keys_ctrl = ['control_l', 'control_r']

        self.ev_intercom = threading.Event()
        self.recorder = Recorder.SoundRecorder()

        # Which system we are connecting to
        self.rohosts = 'g2ins1'

        self.app = Widgets.Application(logger=self.logger)
        self.app.add_callback('shutdown', self.quit)
        self.top = self.app.make_window("Gen2 Display Server")
        self.top.add_callback('close', self.quit)

        vbox = Widgets.VBox()
        vbox.set_border_width(2)
        vbox.set_spacing(1)

        menubar = Widgets.Menubar()

        # create a File pulldown menu, and add it to the menu bar
        filemenu = menubar.add_name('File')

        showlog = filemenu.add_name("Show Log")
        showlog.add_callback('activated', lambda w: self.showlog())

        w = filemenu.add_name("Mute", checkable=True)
        w.set_state(False)
        w.add_callback('activated', self.muteOnOff)

        filemenu.add_separator()

        quit_item = filemenu.add_name("Exit")
        quit_item.add_callback('activated', self.quit)

        # create an Option pulldown menu, and add it to the menu bar
        sysmenu = menubar.add_name('System')

        w = sysmenu.add_name("Summit", checkable=True)
        w.set_state(self.options.rohosts == 'g2ins1')
        w.add_callback('activated', self.select_system, 'g2ins1')

        w = sysmenu.add_name("Simulator", checkable=True)
        w.set_state(self.options.rohosts == 'g2sim')
        w.add_callback('activated', self.select_system, 'g2sim')

        w = sysmenu.add_name("Other", checkable=True)
        w.add_callback('activated', self.select_system, 'other')

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

        fi.add_callback('key-press', self.key_press_event)
        fi.add_callback('key-release', self.key_release_event)
        fi.add_callback('focus', self.focus_event)
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

        quit = Widgets.Button("Quit")
        quit.add_callback('activated', lambda w: self.quit())
        btnbox.add_widget(Widgets.Label(''))
        btnbox.add_widget(quit)
        btnbox.add_widget(Widgets.Label(''))

        vbox.add_widget(btnbox, stretch=0)

        # pop-up log file
        self.tmr_log = GwHelp.Timer(1.0)
        self.tmr_log.add_callback('expired', self.logupdate)
        self.create_logwindow()
        self.create_selector()

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
        guiHdlr.setLevel(logging.DEBUG)
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

    def create_selector(self):
        d = Widgets.Dialog(title='Gen2 System Selector',
                           buttons=(("Ok", 0), ("Cancel", 1)))
        d.add_callback('activated', self.setGen2System)
        d.add_callback('close', lambda w: self.hide_selector())
        self.w.selector = d

        vbox = d.get_content_area()
        w = Widgets.Label('Enter hostname of system')
        vbox.add_widget(w, stretch=0)

        w = Widgets.TextEntry()
        vbox.add_widget(w, stretch=0)
        self.system = w

    def hide_selector(self):
        print("HIDE SELECTOR!")
        self.w.selector.hide()
        return True

    def muteOnOff(self, w, tf):
        # mute audio
        if tf:
            self.obj.muteOn()
        else:
            self.obj.muteOff()

    def get_rohosts(self):
        return self.rohosts

    def restart_servers(self, rohosts):
        self.obj.stop_server()
        time.sleep(1.0)
        self.obj.start_server(rohosts, self.options)

    def select_system(self, menu_w, state, name):
        if not state:
            return True

        # Choose summit or simulator or other
        if name == 'other':
            self.w.selector.show()
            return True
        self.rohosts = name
        self.restart_servers(self.rohosts.split(','))
        return True

    def setGen2System(self, w, res):
        self.w.selector.hide()

        # Choose other system
        if res == 1:
            return True

        self.rohosts = self.system.get_text()
        self.restart_servers(self.rohosts.split(','))

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


    # callback to quit the program
    def quit(self, *args):
        self.obj.allViewersOff()
        self.logger.debug('stopping server')
        self.obj.stop_server()
        self.logger.debug('setting ev_quit')
        self.ev_quit.set()
        self.logger.debug('quitting app')
        self.app.quit()
        self.logger.debug('done quitting')
        return False

    def start_record(self):
        self.ev_intercom.clear()
        self.viewer.onscreen_message("Now recording; release to send")

        self.recorder.recordToWAVbufferSave(self.ev_intercom)

        self.viewer.onscreen_message("Press CTRL to talk")

        buf = self.recorder.getSavedSample()
        self.logger.info("buffer is %d bytes" % len(buf))

        #self.obj.soundsink.playSound(buf, format='wav', decode=False)
        self.obj.soundsource.playSound(buf, format='wav', compress=True)

    def key_press_event(self, viewer, keyname):
        #keyname = event.key
        self.logger.debug("key press event, key=%s" % (keyname))
        if keyname in self.keys_ctrl:
            # TODO: use threadpool?
            t = threading.Thread(target=self.start_record)
            t.start()
        return True

    def key_release_event(self, viewer, keyname):
        #keyname = event.key
        self.logger.debug("key release event, key=%s" % (keyname))
        if (keyname in self.keys_ctrl):
            self.ev_intercom.set()
        return True

    def focus_event(self, viewer, has_focus):
        self.logger.debug("focus event, focus=%s" % (has_focus))
        if not has_focus:
            self.ev_intercom.set()
            #self.viewer.set_bg(0.5, 0.5, 0.5)
            self.viewer.onscreen_message("Move cursor into window to use")
        else:
            self.viewer.onscreen_message("Press CTRL to talk")

        return True


class GraphicalUI(object):

    def __init__(self, options):
        self.options = options
        self.ev_quit = threading.Event()

    def ui(self, obj):
        g2disp = g2Disp_GUI(self.options, obj, self.ev_quit)

        g2disp.logupdate(g2disp.tmr_log)

        rohosts = g2disp.get_rohosts().split(',')
        obj.start_server(rohosts, self.options)

        g2disp.app.mainloop()
