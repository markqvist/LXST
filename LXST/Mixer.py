import RNS
import LXST
import time
import math
import threading
import numpy as np
from collections import deque
from inspect import currentframe
from .Codecs import Codec, Raw
from .Codecs.Codec import resample
from .Sinks import LocalSink
from .Sources import LocalSource, Backend

class Mixer(LocalSource, LocalSink):
    MAX_FRAMES = 8
    TYPE_MAP_FACTOR = np.iinfo("int16").max

    def __init__(self, target_frame_ms=40, samplerate=None, codec=None, sink=None):
        self.incoming_frames  = {}
        self.target_frame_ms  = target_frame_ms
        self.frame_time       = self.target_frame_ms/1000
        self.should_run       = False
        self.mixer_thread     = None
        self.mixer_lock       = threading.Lock()
        self.insert_lock      = threading.Lock()
        self.bitdepth         = 32
        self.channels         = None
        self.samplerate       = None
        self._sink            = None
        self._source          = None
        self._codec           = None

        if samplerate: self.samplerate = samplerate
        if sink:       self.sink       = sink
        if codec:      self.codec      = codec
 
    def start(self):
        if not self.should_run:
            RNS.log(f"{self} starting", RNS.LOG_DEBUG)
            self.should_run = True
            self.mixer_thread = threading.Thread(target=self._mixer_job, daemon=True)
            self.mixer_thread.start()

    def stop(self):
        self.should_run = False

    def can_receive(self, from_source):
        if not from_source in self.incoming_frames:
            return True
        elif len(self.incoming_frames[from_source]) < self.MAX_FRAMES:
            return True
        else:
            return False

    def handle_frame(self, frame, source, decoded=False):
        with self.insert_lock:
            if not source in self.incoming_frames:
                self.incoming_frames[source]  = deque(maxlen=self.MAX_FRAMES)
                
                if not self.channels:
                    self.channels = source.channels

                if not self.samplerate:
                    self.samplerate = source.samplerate
                    self.samples_per_frame = math.ceil((self.target_frame_ms/1000)*self.samplerate)
                    self.frame_time = self.samples_per_frame/self.samplerate
                    RNS.log(f"{self} samplerate set to {RNS.prettyfrequency(self.samplerate)}", RNS.LOG_DEBUG)
                    RNS.log(f"{self} frame time is {RNS.prettyshorttime(self.frame_time)}")

            if not decoded: frame_samples = source.codec.decode(frame)
            else:           frame_samples = frame

            # TODO: Add resampling for all source types
            # if CODEC_OUTPUT_RATE != self.samplerate:
            #     frame_samples = resample(frame_samples, source.bitdepth, source.channels, CODEC_OUTPUT_RATE, self.samplerate)

            self.incoming_frames[source].append(frame_samples)

    def _mixer_job(self):
        with self.mixer_lock:
            while self.should_run:
                if self.sink and self.sink.can_receive():
                    source_count = 0
                    mixed_frame = None
                    for source in self.incoming_frames.copy():
                        if len(self.incoming_frames[source]) > 0:
                            next_frame = self.incoming_frames[source].popleft()
                            if source_count == 0: mixed_frame = next_frame
                            else: mixed_frame = mixed_frame + next_frame
                            source_count += 1

                    if source_count > 0:
                        if self.codec: self.sink.handle_frame(self.codec.encode(mixed_frame), self)
                        else:          self.sink.handle_frame(mixed_frame, self)
                    else:
                        time.sleep(self.frame_time*0.1)

                else:
                    time.sleep(self.frame_time*0.1)

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
                self.samplerate = self.codec.preferred_samplerate
            else:
                self.samplerate = Backend.SAMPLERATE

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

    @property
    def source(self):
        return self._source

    @source.setter
    def source(self, source):
        self._source = source

    @property
    def sink(self):
        return self._sink

    @sink.setter
    def sink(self, sink):
        self._sink = sink

