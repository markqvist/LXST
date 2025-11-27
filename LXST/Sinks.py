import RNS
import math
import time
import threading
import numpy as np
from collections import deque
from LXST.Codecs import Opus
from LXST.Codecs.Codec import resample_bytes, resample

class LinuxBackend():
    SAMPLERATE = 48000

    def __init__(self, preferred_device=None, samplerate=SAMPLERATE):
        from .Platforms.linux import soundcard
        self.samplerate = samplerate
        self.soundcard  = soundcard
        if preferred_device:
            try:    self.device = self.soundcard.get_speaker(preferred_device)
            except: self.device = soundcard.default_speaker()
        else:       self.device = soundcard.default_speaker()
        RNS.log(f"Using output device {self.device}", RNS.LOG_DEBUG)

    def all_speakers(self): return self.soundcard.all_speakers()
    def default_speaker(self): return self.soundcard.default_speaker()

    def flush(self): self.device.flush()

    def get_player(self, samples_per_frame=None, low_latency=None):
        return self.device.player(samplerate=self.samplerate, blocksize=samples_per_frame)

    def release_player(self): pass

class AndroidBackend():
    SAMPLERATE = 48000

    def __init__(self, preferred_device=None, samplerate=SAMPLERATE):
        from .Platforms.android import soundcard
        self.samplerate = samplerate
        self.soundcard  = soundcard
        if preferred_device:
            try:    self.device = self.soundcard.get_speaker(preferred_device)
            except: self.device = soundcard.default_speaker()
        else:       self.device = soundcard.default_speaker()
        RNS.log(f"Using output device {self.device}", RNS.LOG_DEBUG)

    def all_speakers(self): return self.soundcard.all_speakers()
    def default_speaker(self): return self.soundcard.default_speaker()

    def flush(self): self.device.flush()

    def get_player(self, samples_per_frame=None, low_latency=None):
        return self.device.player(samplerate=self.samplerate, blocksize=samples_per_frame, low_latency=low_latency)

    def release_player(self): pass

class DarwinBackend():
    SAMPLERATE = 48000

    def __init__(self, preferred_device=None, samplerate=SAMPLERATE):
        from .Platforms.darwin import soundcard
        self.samplerate = samplerate
        self.soundcard  = soundcard
        if preferred_device:
            try:    self.device = self.soundcard.get_speaker(preferred_device)
            except: self.device = soundcard.default_speaker()
        else:       self.device = soundcard.default_speaker()
        RNS.log(f"Using output device {self.device}", RNS.LOG_DEBUG)

    def all_speakers(self): return self.soundcard.all_speakers()
    def default_speaker(self): return self.soundcard.default_speaker()
    
    def flush(self): self.device.flush()

    def get_player(self, samples_per_frame=None, low_latency=None):
        return self.device.player(samplerate=self.samplerate, blocksize=samples_per_frame)

    def release_player(self): pass

class WindowsBackend():
    SAMPLERATE = 48000

    def __init__(self, preferred_device=None, samplerate=SAMPLERATE):
        from .Platforms.windows import soundcard
        self.samplerate   = samplerate
        self.soundcard    = soundcard
        if preferred_device:
            try:    self.device = self.soundcard.get_speaker(preferred_device)
            except: self.device = soundcard.default_speaker()
        else:       self.device = soundcard.default_speaker()
        RNS.log(f"Using output device {self.device}", RNS.LOG_DEBUG)

    def all_speakers(self): return self.soundcard.all_speakers()
    def default_speaker(self): return self.soundcard.default_speaker()
    
    def flush(self): self.device.flush()

    def get_player(self, samples_per_frame=None, low_latency=None):
        return self.device.player(samplerate=self.samplerate, blocksize=samples_per_frame)

    def release_player(self): pass

def get_backend():
    if RNS.vendor.platformutils.is_linux():     return LinuxBackend
    elif RNS.vendor.platformutils.is_windows(): return WindowsBackend
    elif RNS.vendor.platformutils.is_darwin():  return DarwinBackend
    elif RNS.vendor.platformutils.is_android(): return AndroidBackend
    else:                                       return None

Backend = get_backend()

class Sink():
    def handle_frame(self, frame, source): pass
    def can_receive(self, from_source=None): return True

class RemoteSink(Sink): pass
class LocalSink(Sink): pass

class LineSink(LocalSink):
    MAX_FRAMES    = 6
    AUTOSTART_MIN = 1
    FRAME_TIMEOUT = 8

    def __init__(self, preferred_device=None, autodigest=True, low_latency=False):
        self.preferred_device     = preferred_device
        self.should_run           = False
        self.digest_thread        = None
        self.digest_lock          = threading.Lock()
        self.insert_lock          = threading.Lock()
        self.frame_deque          = deque(maxlen=self.MAX_FRAMES)
        self.underrun_at          = None
        self.frame_timeout        = self.FRAME_TIMEOUT
        self.autodigest           = autodigest
        self.autostart_min        = self.AUTOSTART_MIN
        self.buffer_max_height    = self.MAX_FRAMES-3
        self.low_latency          = low_latency
        
        self.preferred_samplerate = Backend.SAMPLERATE
        self.backend              = Backend(preferred_device=self.preferred_device, samplerate=self.preferred_samplerate)
        self.samplerate           = self.backend.samplerate
        self.channels             = self.backend.device.channels

        self.samples_per_frame    = None
        self.frame_time           = None
        self.output_latency       = 0
        self.max_latency          = 0
        
        self.__wants_low_latency  = False

    def can_receive(self, from_source=None):
        with self.insert_lock:
            if len(self.frame_deque) < self.buffer_max_height: return True
            else:                                              return False

    def handle_frame(self, frame, source=None):
        with self.insert_lock:
            self.frame_deque.append(frame)
        
            if self.samples_per_frame == None:
                self.samples_per_frame = frame.shape[0]
                self.frame_time = self.samples_per_frame*(1/self.backend.samplerate)
                RNS.log(f"{self} starting at {self.samples_per_frame} samples per frame, {self.channels} channels", RNS.LOG_DEBUG)

            if self.autodigest and not self.should_run:
                if len(self.frame_deque) >= self.autostart_min: self.start()

    def start(self):
        if not self.should_run:
            self.should_run = True
            self.digest_thread = threading.Thread(target=self.__digest_job, daemon=True)
            self.digest_thread.start()

    def stop(self):
        self.should_run = False

    def enable_low_latency(self):
        self.__wants_low_latency = True

    def __digest_job(self):
        with self.digest_lock:
            if not RNS.vendor.platformutils.is_darwin(): backend_samples_per_frame = self.samples_per_frame
            else: backend_samples_per_frame = None

            with self.backend.get_player(samples_per_frame=backend_samples_per_frame, low_latency=self.low_latency) as player:
                while self.should_run:
                    frames_ready = len(self.frame_deque)
                    if frames_ready:
                        self.output_latency = len(self.frame_deque)*self.frame_time
                        self.max_latency    = self.buffer_max_height*self.frame_time
                        self.underrun_at    = None

                        with self.insert_lock: frame = self.frame_deque.popleft()
                        if frame.shape[1] > self.channels: frame = frame[:, 0:self.channels]
                        player.play(frame)

                        if len(self.frame_deque) > self.buffer_max_height:
                            RNS.log(f"Buffer lag on {self} (height {len(self.frame_deque)}), dropping one frame", RNS.LOG_DEBUG)
                            self.frame_deque.popleft()
                    
                    else:
                        if self.underrun_at == None:
                            # TODO: Remove debug
                            # RNS.log(f"Buffer underrun on {self}", RNS.LOG_DEBUG)
                            self.underrun_at = time.time()
                        else:
                            if time.time() > self.underrun_at+(self.frame_time*self.frame_timeout):
                                RNS.log(f"No frames available on {self}, stopping playback", RNS.LOG_DEBUG)
                                self.should_run = False
                            else: time.sleep(self.frame_time*0.1)

                    if self.__wants_low_latency:
                        self.__wants_low_latency = False
                        if hasattr(player, "enable_low_latency") and callable(player.enable_low_latency):
                            RNS.log(f"Run-time enabling low-latency mode on {self}", RNS.LOG_DEBUG)
                            player.enable_low_latency()
                        else:
                            RNS.log(f"Could not run-time enable low latency mode on {self}, the operation is not supported by the backend", RNS.LOG_DEBUG)

            self.backend.release_player()

class OpusFileSink(LocalSink):
    MAX_FRAMES       = 64
    AUTOSTART_MIN    = 1
    FINALIZE_TIMEOUT = 2
    TYPE_MAP_FACTOR  = np.iinfo("int16").max

    def __init__(self, path=None, autodigest=True, profile=Opus.PROFILE_AUDIO_MAX):
        self.should_run           = False
        self.digest_thread        = None
        self.digest_lock          = threading.Lock()
        self.insert_lock          = threading.Lock()
        self.frame_deque          = deque(maxlen=self.MAX_FRAMES)
        self.autodigest           = autodigest
        self.autostart_min        = self.AUTOSTART_MIN
        self.buffer_max_height    = self.MAX_FRAMES
        self.profile              = profile
        self.bitdepth             = 32
        self.samplerate           = None
        self.output_samplerate    = Opus.profile_samplerate(self.profile)
        self.channels             = Opus.profile_channels(self.profile)
        self.application          = Opus.profile_application(self.profile)
        self.bitrate_ceiling      = Opus.profile_bitrate_ceiling(self.profile)
        self.max_bytes_per_frame  = None
        self.samples_per_frame    = None
        self.frame_time           = None
        self.output_latency       = 0
        self.max_latency          = 0
        self.underrun_at          = None
        self.samples_written      = 0
        self.__recording_stopped  = False
        self.__finalized          = False
        self.__opus_writer        = None
        self.__encoder            = None
        self.__output_path        = path

    @property
    def frames_waiting(self): return len(self.frame_deque)

    def can_receive(self, from_source=None):
        with self.insert_lock:
            if self.__recording_stopped: return False
            if len(self.frame_deque) < self.buffer_max_height: return True
            else:                                              return False

    def handle_frame(self, frame, source=None):
        with self.insert_lock:
            self.frame_deque.append(frame)
            if self.samples_per_frame == None:
                self.samplerate = source.samplerate
                self.samples_per_frame = frame.shape[0]
                self.frame_time = self.samples_per_frame*(1/self.samplerate)
                if not self.channels: self.channels = frame.shape[1]
                RNS.log(f"{self} starting at {self.samples_per_frame} samples per frame, {self.channels} channels", RNS.LOG_DEBUG)

            if self.autodigest and not self.should_run:
                if len(self.frame_deque) >= self.autostart_min: self.start()

    def start(self):
        if not self.should_run:
            self.should_run = True
            self.digest_thread = threading.Thread(target=self.__digest_job, daemon=True)
            self.digest_thread.start()

    def stop(self):
        if self.should_run:
            self.__recording_stopped = True
            timeout = time.time()+self.FINALIZE_TIMEOUT
            while len(self.frame_deque) > 0 and time.time() < timeout: time.sleep(0.05)
            self.should_run = False
            while self.__finalized == False: time.sleep(0.05)    
            self.__opus_writer.close()
            self.__opus_writer = None

    def __digest_job(self):
        with self.digest_lock:
            from .Codecs.libs.pyogg import OpusBufferedEncoder
            from .Codecs.libs.pyogg import OggOpusWriter
            
            if not self.__output_path: raise ValueError("No recording file path configured")
            self.max_bytes_per_frame = Opus.max_bytes_per_frame(self.bitrate_ceiling, self.frame_time*1000)
            self.__encoder = OpusBufferedEncoder()
            self.__encoder.set_application(self.application)
            self.__encoder.set_sampling_frequency(self.samplerate)
            self.__encoder.set_channels(self.channels)
            self.__encoder.set_frame_size(int(self.frame_time*1000))
            self.__encoder.set_max_bytes_per_frame(self.max_bytes_per_frame)
            self.__opus_writer = OggOpusWriter(self.__output_path, self.__encoder)

            final_silence_frames = 10
            while self.should_run or final_silence_frames > 0:
                frames_ready = len(self.frame_deque) or (self.should_run == False and final_silence_frames)
                if frames_ready:
                    self.output_latency = len(self.frame_deque)*self.frame_time
                    self.max_latency    = self.buffer_max_height*self.frame_time
                    self.underrun_at    = None
                    
                    if self.should_run:
                        with self.insert_lock: frame = self.frame_deque.popleft()
                    else:
                        final_silence_frames -= 1
                        frame = np.zeros((self.samples_per_frame, self.channels), dtype="float32")

                    if   frame.shape[1] > self.channels: frame = frame[:, 0:self.channels]
                    elif frame.shape[1] < self.channels:
                        for i in range(self.channels - frame.shape[1]):
                            frame = np.hstack([frame, frame[:, -1:]])

                    if frame.shape[0] < self.samples_per_frame:
                        RNS.log("Insufficient frame data, padding with silence", RNS.LOG_DEBUG)
                        silence_frame = np.zeros((self.samples_per_frame-frame.shape[0], frame.shape[1]), dtype=frame.dtype)
                        frame = np.vstack([frame, silence_frame])

                    self.samples_written += frame.shape[0]

                    if self.samplerate != 48000:
                        frame = resample(frame, self.bitdepth, self.channels, self.samplerate, self.output_samplerate)

                    input_samples = frame*self.TYPE_MAP_FACTOR
                    input_samples = input_samples.astype(np.int16)

                    self.__opus_writer.write(bytearray(input_samples.tobytes()))
                    
                    if len(self.frame_deque) > self.buffer_max_height: RNS.log(f"Buffer lag on {self} (height {len(self.frame_deque)})", RNS.LOG_DEBUG)
                else:
                    if self.underrun_at == None: self.underrun_at = time.time()
                    else: time.sleep(self.frame_time*0.1)

            self.__finalized = True
