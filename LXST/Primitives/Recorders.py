import RNS
import LXST
import time
import os
from LXST.Sources import LineSource
from LXST.Sinks import OpusFileSink
from LXST.Filters import BandPass, AGC

class FileRecorder():
    def __init__(self, path=None, device=None, profile=LXST.Codecs.Opus.PROFILE_AUDIO_MAX,
                 gain=0.0, ease_in=0.125, skip=0.075, filters=[BandPass(25, 24000)]):
        self._file_path = path
        self._record_device = device
        self.__profile = profile
        self.__source = None
        self.__sink = OpusFileSink(path=self._file_path, profile=profile)
        self.__null = LXST.Codecs.Null()
        self.__filters = filters
        self.__ease_in = ease_in
        self.__skip = skip
        self.__gain = gain
        self.set_source(device)

    @property
    def running(self):
        if not self.__source: return False
        else: return self.__source.should_run

    @property
    def recording(self): return self.running

    def set_source(self, device=None):
        self._record_device = device
        self.__source = LineSource(preferred_device=self._record_device, target_frame_ms=20, codec=self.__null, sink=self.__sink,
                                   gain=self.__gain, ease_in=self.__ease_in, skip=self.__skip, filters=self.__filters)
        self.__sink.source = self.__source

    def set_output_path(self, path):
        self._file_path = path
        self.__sink.__output_path = path

    def start(self):
        if self.__source:
            self.__source.start()

    def stop(self):
        if self.__source:
            self.__source.stop()
            while self.__sink.frames_waiting: time.sleep(0.1)
            self.__sink.stop()

    def record(self): 
        self.start()