import os
import RNS
import math
import time
import threading
import numpy as np
from collections import deque
from .Sinks import LocalSink
from .Codecs import Codec, CodecError
from .Codecs.libs.pyogg import OpusFile

RNS.loglevel = RNS.LOG_DEBUG

class LinuxBackend():
    SAMPLERATE = 48000

    def __init__(self, preferred_device=None, samplerate=SAMPLERATE):
        import soundcard
        self.samplerate = samplerate
        self.soundcard  = soundcard
        if preferred_device:
            try:    self.device = self.soundcard.get_microphone(preferred_device)
            except: self.device = self.soundcard.default_microphone()
        else:       self.device = self.soundcard.default_microphone()
        self.channels   = self.device.channels
        self.bitdepth   = 32
        RNS.log(f"Using input device {self.device}", RNS.LOG_DEBUG)

    def flush(self):
        self.recorder.flush()

    def get_recorder(self, samples_per_frame):
        return self.device.recorder(samplerate=self.SAMPLERATE, blocksize=samples_per_frame)

def get_backend():
    if RNS.vendor.platformutils.is_linux():
        return LinuxBackend
    else:
        return None

Backend = get_backend()

class Source():
    pass

class LocalSource(Source):
    pass

class RemoteSource(Source):
    pass

class Loopback(LocalSource, LocalSink):
    MAX_FRAMES = 128

    def __init__(self, target_frame_ms=70, codec=None, sink=None):
        self.frame_deque     = deque(maxlen=self.MAX_FRAMES)
        self.should_run      = False
        self.loopback_thread = None
        self.loopback_lock   = threading.Lock()
        self.codec           = codec
        self._sink           = sink
        self._source         = None

    def start(self):
        if not self.should_run:
            RNS.log(f"{self} starting", RNS.LOG_DEBUG)
            self.should_run = True

    def stop(self):
        self.should_run = False

    def can_receive(self, from_source=None):
        if self._sink:
            return self._sink.can_receive(from_source)
        else:
            return True

    def handle_frame(self, frame, source):
        with self.loopback_lock:
            if self.codec and self.sink:
                self.sink.handle_frame(self.codec.decode(frame), self)

    @property
    def source(self):
        return self._source

    @source.setter
    def source(self, source):
        self._source = source

class LineSource(LocalSource):
    MAX_FRAMES       = 128
    DEFAULT_FRAME_MS = 80

    def __init__(self, preferred_device=None, target_frame_ms=DEFAULT_FRAME_MS, codec=None, sink=None):
        self.preferred_device = preferred_device
        self.frame_deque      = deque(maxlen=self.MAX_FRAMES)
        self.target_frame_ms  = target_frame_ms
        self.samplerate       = None
        self.channels         = None
        self.bitdepth         = None
        self.should_run       = False
        self.ingest_thread    = None
        self.recording_lock   = threading.Lock()
        self._codec           = None
        self.codec            = codec
        self.sink             = sink

    @property
    def codec(self):
        return self._codec

    @codec.setter
    def codec(self, codec):
        if codec == None:
            self._codec = None
        elif not issubclass(type(codec), Codec):
            raise CodecError(f"Invalid codec specified for {self}")
        else:
            self._codec = codec

            if self.codec.preferred_samplerate:
                self.preferred_samplerate = self.codec.preferred_samplerate
            else:
                self.preferred_samplerate = Backend.SAMPLERATE

            if self.codec.frame_quanta_ms:
                if self.target_frame_ms%self.codec.frame_quanta_ms != 0:
                    self.target_frame_ms = math.ceil(self.target_frame_ms/self.codec.frame_quanta_ms)*self.codec.frame_quanta_ms
                    RNS.log(f"{self} target frame time quantized to {self.target_frame_ms}ms due to codec frame quanta", RNS.LOG_DEBUG)
            
            if self.codec.frame_max_ms:
                if self.target_frame_ms > self.codec.frame_max_ms:
                    self.target_frame_ms = self.codec.frame_max_ms
                    RNS.log(f"{self} target frame time clamped to {self.target_frame_ms}ms due to codec frame limit", RNS.LOG_DEBUG)

            if self.codec.valid_frame_ms:
                if not self.target_frame_ms in self.codec.valid_frame_ms:
                    self.target_frame_ms = min(self.codec.valid_frame_ms, key=lambda t:abs(t-self.target_frame_ms))
                    RNS.log(f"{self} target frame time clamped to closest valid value of {self.target_frame_ms}ms ", RNS.LOG_DEBUG)

            self.backend           = Backend(preferred_device=self.preferred_device, samplerate=self.preferred_samplerate)
            self.samplerate        = self.backend.samplerate
            self.bitdepth          = self.backend.bitdepth
            self.channels          = self.backend.channels
            self.samples_per_frame = math.ceil((self.target_frame_ms/1000)*self.samplerate)

    def start(self):
        if not self.should_run:
            RNS.log(f"{self} starting at {self.samples_per_frame} samples per frame, {self.channels} channels", RNS.LOG_DEBUG)
            self.should_run = True
            self.ingest_thread = threading.Thread(target=self.__ingest_job, daemon=True)
            self.ingest_thread.start()

    def stop(self):
        self.should_run = False

    def __ingest_job(self):
        with self.recording_lock:
            frame_samples = None
            with self.backend.get_recorder(samples_per_frame=self.samples_per_frame) as recorder:
                while self.should_run:
                    frame_samples = recorder.record(numframes=self.samples_per_frame)
                    if self.codec:
                        frame = self.codec.encode(frame_samples)
                        if self.sink and self.sink.can_receive(from_source=self):
                            self.sink.handle_frame(frame, self)

class OpusFileSource(LocalSource):
    MAX_FRAMES       = 128
    DEFAULT_FRAME_MS = 70
    TYPE_MAP_FACTOR  = np.iinfo("int16").max

    def __init__(self, file_path, target_frame_ms=DEFAULT_FRAME_MS, loop=False, codec=None, sink=None, timed=False):
        self.target_frame_ms = target_frame_ms
        self.loop            = loop
        self.timed           = timed
        self.read_lock       = threading.Lock()
        self.should_run      = False
        self.ingest_thread   = None
        self.next_frame      = None
        self._codec          = None

        if file_path == None:
            raise TypeError(f"{self} initialised with invalid file path: {file_path}")
        elif os.path.isfile(file_path):
            self.file = OpusFile(file_path)
            self.samplerate = self.file.frequency
            self.channels = self.file.channels
            self.bitdepth = 16
            self.samples = self.file.as_array()/self.TYPE_MAP_FACTOR
            self.sample_count = self.samples.shape[0]
            self.length_ms = (self.sample_count/self.samplerate)*1000
            RNS.log(f"{self} loaded {RNS.prettytime(self.length_ms/1000)} of audio from {file_path}", RNS.LOG_DEBUG)
            RNS.log(f"{self} samplerate is {RNS.prettyfrequency(self.samplerate)}, {self.channels} channels, {self.sample_count} samples in total", RNS.LOG_DEBUG)
        else:
            raise OSError(f"{self} file {file_path} not found")

        self.codec           = codec
        self.sink            = sink

    @property
    def codec(self):
        return self._codec

    @codec.setter
    def codec(self, codec):
        if codec == None:
            self._codec = None
        elif not issubclass(type(codec), Codec):
            raise CodecError(f"Invalid codec specified for {self}")
        else:
            self._codec = codec

            if self.codec.frame_quanta_ms:
                if self.target_frame_ms%self.codec.frame_quanta_ms != 0:
                    self.target_frame_ms = math.ceil(self.target_frame_ms/self.codec.frame_quanta_ms)*self.codec.frame_quanta_ms
                    RNS.log(f"{self} target frame time quantized to {self.target_frame_ms}ms due to codec frame quanta", RNS.LOG_DEBUG)
            
            if self.codec.frame_max_ms:
                if self.target_frame_ms > self.codec.frame_max_ms:
                    self.target_frame_ms = self.codec.frame_max_ms
                    RNS.log(f"{self} target frame time clamped to {self.target_frame_ms}ms due to codec frame limit", RNS.LOG_DEBUG)

            if self.codec.valid_frame_ms:
                if not self.target_frame_ms in self.codec.valid_frame_ms:
                    self.target_frame_ms = min(self.codec.valid_frame_ms, key=lambda t:abs(t-self.target_frame_ms))
                    RNS.log(f"{self} target frame time clamped to closest valid value of {self.target_frame_ms}ms ", RNS.LOG_DEBUG)

            self.samples_per_frame = math.ceil((self.target_frame_ms/1000)*self.samplerate)
            self.frame_time = self.samples_per_frame/self.samplerate
            RNS.log(f"{self} frame time is {RNS.prettyshorttime(self.frame_time)}", RNS.LOG_DEBUG)

    def start(self):
        if not self.should_run:
            RNS.log(f"{self} starting at {self.samples_per_frame} samples per frame, {self.channels} channels", RNS.LOG_DEBUG)
            self.should_run = True
            self.ingest_thread = threading.Thread(target=self.__ingest_job, daemon=True)
            self.ingest_thread.start()

    def stop(self):
        self.should_run = False

    def __ingest_job(self):
        with self.read_lock:
            self.next_frame = time.time()
            fi = 0; spf = self.samples_per_frame; sc = self.sample_count
            while self.should_run:
                if self.sink and self.sink.can_receive(from_source=self) and (not self.timed or time.time() >= self.next_frame):
                    self.next_frame = time.time()+self.frame_time
                    fi += 1
                    fs = (fi-1)*spf; fe = min(fi*spf, sc)
                    frame_samples = self.samples[fs:fe, :]
                    if len(frame_samples) < 1:
                        if self.loop:
                            RNS.log(f"{self} exhausted file samples, looping...", RNS.LOG_DEBUG)
                            fi = 0
                        else:
                            RNS.log(f"{self} exhausted file samples, stopping...", RNS.LOG_DEBUG)
                            self.should_run = False
                    else:
                        if self.codec:
                            frame = self.codec.encode(frame_samples)
                            if self.sink and self.sink.can_receive(from_source=self):
                                self.sink.handle_frame(frame, self)
                else:
                    time.sleep(self.frame_time*0.1)

class PacketSource(RemoteSource):
    pass