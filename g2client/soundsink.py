#!/usr/bin/env python
#
# Eric Jeschke (eric@naoj.org)
#
"""
The Gen2 distributed sound system (SoundSink/SoundSource).
"""
from __future__ import print_function
from __future__ import absolute_import
import sys, os
import time
import threading
import hashlib
import tempfile
from g2base.six.moves import queue as Queue

from g2base.remoteObjects import remoteObjects as ro
from g2base.remoteObjects import Monitor
from g2base import ssdlog, Task


# Default ports
default_svc_port = 15051
default_mon_port = 15052

# Sound device to use for audio when playing sounds locally
default_sound_dev = "/dev/audio"


# TODO: put this in a utilities module
def error(msg, exitcode=0):
    """Called for an error.  Print _msg_ to stderr and exit program
    with code _exitcode_ if _exitcode_ is set to non-zero.
    """
    sys.stderr.write(msg + '\n')
    if exitcode != 0:
        sys.exit(exitcode)


class SoundBase(object):

    def __init__(self, **kwdargs):
        self.__dict__.update(kwdargs)
        self.lock = threading.RLock()
        self.muted = kwdargs.get('muted', False)

        self.threadPool = self.monitor.get_threadPool()
        self.shares = ['logger', 'threadPool']

    def muteOn(self):
        self.logger.info("turning mute ON")
        with self.lock:
            self.muted = True
        return 0

    def muteOff(self):
        self.logger.info("turning mute OFF")
        with self.lock:
            self.muted = False
        return 0

    def server_loop(self):
        self.logger.info("Sound server starting...")
        while not self.ev_quit.is_set():
            try:
                filepath = self.queue.get(block=True, timeout=0.1)

                self.playFile(filepath)

            except Queue.Empty:
                continue

        self.logger.info("Sound server terminating...")

    def play(self, filepath):
        self.logger.debug("Enqueing file %s..." % (filepath))
        self.queue.put(filepath)
        return 0


class SoundSource(SoundBase):

    def __init__(self, **kwdargs):
        super(SoundSource, self).__init__(**kwdargs)

        self.tag = 'mon.sound.sound0'

    def _playSound(self, buffer, format=None, encode=True, compress=None,
                   filename=None, priority=20, dst='all'):

        ## if compress == None:
        ##     compress = self.compress

        with self.lock:
            if self.muted:
                self.logger.warn("play sound buffer: mute is ON")
                return ro.OK

        if compress:
            beforesize = len(buffer)
            buffer = ro.compress(buffer)
            aftersize = len(buffer)
            self.logger.debug("Compressed audio buffer %d->%d bytes." % (
                    beforesize, aftersize))

        if encode:
            buffer = ro.binary_encode(buffer)
            self.logger.debug("Encoded audio buffer for transport.")

        try:
            self.monitor.setvals(self.channels, self.tag,
                                 buffer=buffer, format=format,
                                 filename=filename,
                                 compressed=compress,
                                 priority=priority, dst=dst)

        except Exception as e:
            self.logger.error("Error submitting remote sound: %s" % str(e))

    def playSound(self, buffer, format=None, encode=True, compress=None,
                  priority=20, dst='all'):
        t = Task.FuncTask2(self._playSound, buffer, format=format,
                           encode=encode, compress=compress,
                           priority=priority, dst=dst)
        t.init_and_start(self)
        return ro.OK

    def _playFile(self, file, format=None, encode=True, compress=None,
                  priority=20, dst='all'):
        with self.lock:
            if self.muted:
                self.logger.warn("play sound buffer: mute is ON")
                return ro.OK

        dirname, filename = os.path.split(file)

        try:
            with open(file, 'rb') as in_f:
                buffer = in_f.read()

            self._playSound(buffer, format=format, filename=filename,
                            encode=encode, compress=compress,
                            priority=priority, dst=dst)

        except Exception as e:
            self.logger.error("Error submitting remote sound: %s" % str(e))

    def playFile(self, file, format=None, encode=True, compress=None,
                 priority=20, dst='all'):
        t = Task.FuncTask2(self._playFile, file, format=format,
                           encode=encode, compress=compress,
                           priority=priority, dst=dst)
        t.init_and_start(self)
        return ro.OK

    def _playText(self, text, voice='slt', volume=0,
                  encode=True, compress=None, priority=20, dst='all'):
        # TODO: figure out volume options
        hashobj = hashlib.sha256()
        combo = text + voice + str(volume)
        hashobj.update(combo.encode())
        fname = hashobj.hexdigest() + '.wav'
        sndpath = os.path.join("/tmp", fname)
        # see if we need to create this sound file--there will be a cached
        # copy if all the parameters are the same and we have generated one
        # recently
        if not os.path.exists(sndpath):
            tmppath = os.path.join('/tmp', 'snd' + str(time.time()) + '.wav')
            cmd_str = 'flite -t "%s" -voice "%s" -o %s' % (text, voice, tmppath)
            res = os.system(cmd_str)
            if res != 0:
                self.logger.error("Error creating WAV sound file: res=%d" % (res))
                return

            # We have to manually increase or decrease the volume on the
            # file because flite doesn't seem to give us this control...*sigh*
            cmd_str = 'sox %s %s vol %ddb' % (tmppath, sndpath, volume)
            res = os.system(cmd_str)
            os.remove(tmppath)
            if res != 0:
                self.logger.error("Error setting volume of sound file: res=%d" % (res))
                return

        self._playFile(sndpath, format='wav', encode=encode,
                       compress=compress, priority=priority, dst=dst)

    def playText(self, text, voice='slt', volume=None,
                 encode=True, compress=None, priority=20, dst='all':
        """
        TTS text-to-sound service.

        NOTE: this requires that the `flite` and `sox` programs be installed
        on the system running the soundsink server.
        """
        t = Task.FuncTask2(self._playText, text, voice=voice, volume=volume,
                           encode=encode, compress=compress,
                           priority=priority, dst=dst)
        t.init_and_start(self)
        return ro.OK


class SoundSink(SoundBase):

    def __init__(self, **kwdargs):
        super(SoundSink, self).__init__(**kwdargs)

        self.sound_dev = kwdargs.get('sound_dev', default_sound_dev)
        self.playcmd = "paplay"
        #self.playcmd = "play -q"
        self.lock_sound = threading.Lock()
        self.count = 0
        self.maxcount = 20
        self.playcond = threading.Condition()
        self.priority_list = []
        self.waitval = 0.150
        self.dst = set(['all', 'summit'])
        dst = kwdargs.get('dst', None)
        if dst is not None:
            self.dst.add(dst)

        self.tag = 'soundsink'

    def _playSound_bg(self, buffer, filename=None, decode=True,
                      format=None, decompress=False, priority=20):

        # First thing is to add our priority to the priority list
        # so it will be noticed by any other threads playing sounds
        with self.lock_sound:
            self.priority_list.append(priority)

        # Record start time and add interval we should wait before playing
        time_start = time.time()
        time_limit = time_start + self.waitval

        try:
            try:
                # Decode binary data
                if decode:
                    data = ro.binary_decode(buffer)
                else:
                    data = buffer

                # Decompress data if necessary
                if decompress:
                    data = ro.uncompress(data)

                # If format is not explicitly provided, then assume 'au' and
                # override if a filename was given with an extension
                if not format:
                    format = 'au'
                    if filename:
                        dirname, filename = os.path.split(filename)
                        pfx, ext = os.path.splitext(filename)
                        format = ext[1:].lower()

                # Get a temp filename and write out our buffer to a file
                with self.lock_sound:
                    self.count = (self.count + 1) % self.maxcount
                    tmpfile = "_snd%d_%d.%s" % (
                        os.getpid(), self.count, format)

                tmppath = os.path.join('/tmp', tmpfile)
                with open(tmppath, 'wb') as out_f:
                    out_f.write(data)

                # Now sleep the remaining time until our required delay
                # time is reached.  This allows a small window in which
                # other sounds with higher priority might reach us and
                # be played first
                time_delta = time_limit - time.time()
                if time_delta > 0:
                    self.logger.debug("Sleeping for %.3f sec" % (time_delta))
                    time.sleep(time_delta)

                # Acquire the condition and then check the highest priority
                # in the queue.  If there are sounds with higher priority
                # then wait until we are notified.
                with self.playcond:
                    with self.lock_sound:
                        minval = min(self.priority_list)
                    self.logger.info("minval: %d priority: %d list: %s" % (
                        minval, priority, self.priority_list))

                    while minval < priority:
                        self.playcond.wait()
                        self.logger.debug("awakened by notifier!")
                        with self.lock_sound:
                            minval = min(self.priority_list)
                        self.logger.info("minval: %d priority: %d list: %s" % (
                            minval, priority, self.priority_list))

                # Play the file and remove the temp file
                cmd_str = "%s %s" % (
                    self.playcmd, tmppath)
                self.logger.info("Play command is: %s" % cmd_str)
                res = os.system(cmd_str)
                #os.remove(tmppath)

            except (IOError, OSError) as e:
                self.logger.error("Failed to play sound buffer: %s" % (
                    str(e)))
        finally:
            # Finally, remove our priority from the list and notify any
            # waiters (presumably with lower priority).
            with self.playcond:
                with self.lock_sound:
                    self.priority_list.remove(priority)
                    self.playcond.notifyAll()


    def playSound_bg(self, buffer, filename=None, decode=True,
                     format=None, decompress=False, priority=20):
        t = Task.FuncTask2(self._playSound_bg, buffer, format=format,
                           filename=filename, decode=decode,
                           decompress=decompress, priority=priority)
        t.init_and_start(self)

    def playSound(self, buffer, format=None,
                  filename=None, decode=True, decompress=False,
                  priority=20):
        with self.lock:
            if self.muted:
                self.logger.warn("play sound buffer: mute is ON")
                return ro.OK

            self.playSound_bg(buffer, format=format,
                              filename=filename, decode=decode,
                              decompress=decompress, priority=priority)
            return ro.OK

    def playFile(self, file, format=None, decode=False, decompress=False,
                 priority=20):
        with self.lock:
            if self.muted:
                self.logger.warn("play sound buffer: mute is ON")
                return ro.OK

            try:
                with open(file, 'rb') as in_f:
                    data = in_f.read()

                dirname, filename = os.path.split(file)

                return self.playSound_bg(data, format=format,
                                         filename=filename,
                                         decode=False, decompress=decompress,
                                         priority=priority)

            except Exception as e:
                self.logger.error("Error submitting remote sound: %s" % str(e))
                return ro.ERROR

    # define callback functions for the monitor

    # this one is called if new data becomes available
    def anon_arr(self, payload, names, channels):
        self.logger.debug("received values '%s'" % (str(payload)))
        try:
            bnch = Monitor.unpack_payload(payload)

        except Monitor.MonitorError:
            self.logger.error("malformed packet '%s': %s" % (
                str(payload), str(e)))
            return

        info = bnch.value
        #self.logger.debug("info is: %s" % (str(info.keys())))

        # check destination for sound matches (assume None is same as 'all')
        dsts = info.get('dst', 'all')
        if dsts is not None:
            dsts = set(dsts.split(',')).intersection(self.dst)
            if len(dsts) == 0:
                return

        self.playSound(info['buffer'], filename=info['filename'],
                       decode=True, format=info['format'],
                       decompress=info['compressed'],
                       priority=info['priority'])


def main(options, args):

    basename = options.svcname
    logger = ssdlog.make_logger(basename, options)

    # Initialize remote objects subsystem
    try:
        ro.init()

    except ro.remoteObjectError as e:
        logger.error("Error initializing remote objects subsystem: %s" % \
                     str(e))
        sys.exit(1)

    ev_quit = threading.Event()

    # Create a local pub sub instance
    monname = '%s.mon' % basename
    minimon = Monitor.Monitor(monname, logger, numthreads=options.numthreads)

    threadPool = minimon.get_threadPool()

    queue = Queue.Queue()

    channels = options.channels.split(',')

    # Make our callback object/remote object
    if options.soundsink:
        mobj = SoundSink(monitor=minimon, logger=logger, queue=queue,
                         channels=channels, ev_quit=ev_quit,
                         dst=options.destination)
    else:
        mobj = SoundSource(monitor=minimon, logger=logger, queue=queue,
                           channels=channels, ev_quit=ev_quit,
                           compress=options.compress)

    svc = ro.remoteObjectServer(svcname=basename,
                                obj=mobj, logger=logger,
                                port=options.port,
                                ev_quit=ev_quit,
                                usethread=True, threadPool=threadPool)

    mon_server_started = False
    ro_server_started = False
    try:
        # Startup monitor threadpool
        minimon.start(wait=True)
        minimon.start_server(wait=True, port=options.monport)
        mon_server_started = True

        # Configure logger for logging via our monitor
        # if options.logmon:
        #     minimon.logmon(logger, options.logmon, ['logs'])

        if options.soundsink:
            # Subscribe our callback functions to the local monitor
            minimon.subscribe_cb(mobj.anon_arr, channels)
            minimon.subscribe_remote(options.monitor, channels, {})
        else:
            # publish our channels to the specified monitor
            minimon.publish_to(options.monitor, channels, {})


        svc.ro_start(wait=True)
        ro_server_started = True

        try:
            mobj.server_loop()

        except KeyboardInterrupt:
            logger.error("Received keyboard interrupt!")

    finally:
        ev_quit.set()
        if mon_server_started:
            minimon.stop_server(wait=True)
        if ro_server_started:
            svc.ro_stop(wait=True)
        minimon.stop(wait=True)

    logger.info("%s exiting..." % basename)


#END
