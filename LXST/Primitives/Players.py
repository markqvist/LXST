# Copyright 2024-2026, Mark Qvist

import LXST
import time
import threading
import os
import gc

from LXST.Sinks import LineSink
from LXST.Sources import OpusFileSource

class FilePlayer():
    def __init__(self, path=None, device=None, loop=False, gain=0.0, release_on_finish=False):
        self._file_path = path
        self._playback_device = None
        self.__finished_callback = None
        self.__release_on_finish = release_on_finish
        self.__loop = loop
        self.__source = None
        self.__gain = gain
        self.__sink = LineSink(self._playback_device)
        self.__raw             = LXST.Codecs.Raw()
        self.__loopback        = LXST.Sources.Loopback()
        self.__output_pipeline = LXST.Pipeline(source=self.__loopback, codec=self.__raw, sink=self.__sink)
        self.__input_pipeline  = None
        if path: self.set_source(self._file_path)

    @property
    def gain(self): return self.__gain

    @gain.setter
    def gain(self, db):
        try: db = float(db)
        except: raise TypeError("Invalid gain type, must be decibel as a floating point number")
        self.__gain = db
        if self.__source: self.__source.gain = self.__gain

    @property
    def running(self):
        if not self.__source: return False
        else: return self.__source.should_run or len(self.__sink.frame_deque)

    @property
    def playing(self): return self.running

    @property
    def release_on_finish(self): return self.__release_on_finish

    @release_on_finish.setter
    def release_on_finish(self, value):
        if type(value) != bool: raise TypeError("Provided value is not bool")
        else:                   self.__release_on_finish = value

    @property
    def finished_callback(self): return self.__finished_callback

    @finished_callback.setter
    def finished_callback(self, callback):
        if   callback == None:       self.__finished_callback = None
        elif not callable(callback): raise TypeError("Provided callback is not callable")
        else:                        self.__finished_callback = callback

    def __callback_job(self):
        if self.__finished_callback or self.__release_on_finish:
            time.sleep(0.2)
            while self.running: time.sleep(0.1)
            if self.__finished_callback: self.__finished_callback(self)
            if self.__release_on_finish: self.release()

    def set_source(self, path=None):
        if not path: return
        else:
            if not os.path.isfile(path): raise OSError(f"File not found: {path}")
            else:
                self.__source = OpusFileSource(path, loop=self.__loop, gain=self.gain)
                self.__input_pipeline = LXST.Pipeline(source=self.__source, codec=self.__raw, sink=self.__loopback)

    def loop(self, loop=True):
        if loop == True: self.__loop = True
        else: self.__loop = False
        if self.__source: self.__source.loop = self.__loop

    def start(self):
        if not self.running and self.__source:
            self.__input_pipeline.start()
            self.__output_pipeline.start()
            if self.__finished_callback or self.__release_on_finish:
                threading.Thread(target=self.__callback_job, daemon=True).start()

    def stop(self):
        if self.running and self.__source:
            self.__input_pipeline.stop()
            self.__output_pipeline.stop()

    def play(self): self.start()

    def release(self):
        self.stop()
        self.__source.release()
        self.__input_pipeline.release()
        self.__output_pipeline.release()
        self.__input_pipeline = None
        self.__output_pipeline = None
        self.__sink = None
        self.__source = None
        self.__loopback = None