import os
import RNS
import math
import time
import threading
import numpy as np
from collections import deque
from .Codecs import Codec, CodecError
from .Sources import LocalSource

class ToneSource(LocalSource):
    DEFAULT_FRAME_MS   = 80
    DEFAULT_SAMPLERATE = 48000
    DEFAULT_FREQUENCY  = 400
    EASE_TIME_MS       = 20

    def __init__(self, frequency=DEFAULT_FREQUENCY, gain=0.1, ease=True, ease_time_ms=EASE_TIME_MS,
                 target_frame_ms=DEFAULT_FRAME_MS, codec=None, sink=None, channels=1):

        self.target_frame_ms = target_frame_ms
        self.samplerate      = self.DEFAULT_SAMPLERATE
        self.channels        = channels
        self.bitdepth        = 32
        self.frequency       = frequency
        self._gain           = gain
        self.gain            = self._gain
        self.ease            = ease
        self.theta           = 0
        self.ease_gain       = 0
        self.ease_time_ms    = ease_time_ms
        self.ease_step       = 0
        self.gain_step       = 0
        self.easing_out      = False
        self.should_run      = False
        self.generate_thread = None
        self.generate_lock   = threading.Lock()
        self._codec          = None
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

            if self.codec.preferred_samplerate:
                self.samplerate = self.codec.preferred_samplerate

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
            self.ease_step = 1/(self.samplerate*(self.ease_time_ms/1000))
            self.gain_step = 0.02/(self.samplerate*(self.ease_time_ms/1000))

    def start(self):
        if not self.should_run:
            RNS.log(f"{self} starting at {self.samples_per_frame} samples per frame, {self.channels} channels", RNS.LOG_DEBUG)
            self.ease_gain = 0 if self.ease else 1
            self.should_run = True
            self.generate_thread = threading.Thread(target=self.__generate_job, daemon=True)
            self.generate_thread.start()

    def stop(self):
        if not self.ease:
            self.should_run = False
        else:
            self.easing_out = True

    @property
    def running(self):
        return self.should_run and not self.easing_out

    def __generate(self):
        frame_samples = np.zeros((self.samples_per_frame, self.channels), dtype="float32")
        step = (self.frequency * 2 * math.pi) / self.samplerate
        for n in range(0, self.samples_per_frame):
            self.theta += step
            amplitude = math.sin(self.theta)*self._gain*self.ease_gain
            for c in range(0, self.channels):
                frame_samples[n, c] = amplitude

            if self.gain > self._gain:
                self._gain += self.gain_step
                if self._gain > self.gain: self._gain = self.gain

            if self.gain < self._gain:
                self._gain -= self.gain_step
                if self._gain < self.gain: self._gain = self.gain

            if self.ease:
                if self.ease_gain < 1.0 and not self.easing_out:
                    self.ease_gain += self.ease_step
                    if self.ease_gain > 1.0: self.ease_gain = 1.0
                elif self.easing_out and self.ease_gain > 0.0:
                    self.ease_gain -= self.ease_step
                    if self.ease_gain <= 0.0:
                        self.ease_gain = 0.0
                        self.easing_out = False
                        self.should_run = False

        return frame_samples

    def __generate_job(self):
        with self.generate_lock:
            while self.should_run:
                if self.codec and self.sink and self.sink.can_receive(from_source=self):
                    frame_samples = self.__generate()
                    self.last_samples = frame_samples
                    frame = self.codec.encode(frame_samples)
                    self.sink.handle_frame(frame, self)
                time.sleep(self.frame_time*0.1)
