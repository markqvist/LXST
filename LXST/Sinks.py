import RNS
import math
import time
import threading
from collections import deque

class LinuxBackend():
    SAMPLERATE = 48000

    def __init__(self, preferred_device=None, samplerate=SAMPLERATE):
        import soundcard
        self.samplerate = samplerate
        self.soundcard  = soundcard
        if preferred_device:
            try:    self.device = self.soundcard.get_speaker(preferred_device)
            except: self.device = soundcard.default_speaker()
        else:       self.device = soundcard.default_speaker()
        RNS.log(f"Using output device {self.device}", RNS.LOG_DEBUG)

    def flush(self):
        self.recorder.flush()

    def get_player(self, samples_per_frame=None):
        return self.device.player(samplerate=self.samplerate, blocksize=samples_per_frame)

def get_backend():
    if RNS.vendor.platformutils.is_linux():
        return LinuxBackend
    else:
        return None

Backend = get_backend()

class Sink():
    def handle_frame(self, frame, source):
        pass

    def can_receive(self, from_source=None):
        return True

class RemoteSink(Sink):
    pass

class LocalSink(Sink):
    pass

class LineSink(LocalSink):
    MAX_FRAMES    = 6
    AUTOSTART_MIN = 1
    FRAME_TIMEOUT = 8

    def __init__(self, preferred_device=None, autodigest=True):
        self.preferred_device     = preferred_device
        self.frame_deque          = deque(maxlen=self.MAX_FRAMES)
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
        
        self.preferred_samplerate = Backend.SAMPLERATE
        self.backend              = Backend(preferred_device=self.preferred_device, samplerate=self.preferred_samplerate)
        self.samplerate           = self.backend.samplerate
        self.channels             = self.backend.device.channels

        self.samples_per_frame    = None
        self.frame_time           = None
        self.output_latency       = 0
        self.max_latency          = 0

    def can_receive(self, from_source=None):
        with self.insert_lock:
            if len(self.frame_deque) < self.buffer_max_height:
                return True
            else:
                return False

    def handle_frame(self, frame, source=None):
        with self.insert_lock:
            self.frame_deque.append(frame)
        
            if self.samples_per_frame == None:
                self.samples_per_frame = frame.shape[0]
                self.frame_time = self.samples_per_frame*(1/self.backend.samplerate)
                RNS.log(f"{self} starting at {self.samples_per_frame} samples per frame, {self.channels} channels", RNS.LOG_DEBUG)

            if self.autodigest and not self.should_run:
                if len(self.frame_deque) >= self.autostart_min:
                    self.start()

    def start(self):
        if not self.should_run:
            self.should_run = True
            self.digest_thread = threading.Thread(target=self.__digest_job, daemon=True)
            self.digest_thread.start()

    def stop(self):
        self.should_run = False

    def __digest_job(self):
        with self.digest_lock:
            with self.backend.get_player(samples_per_frame=self.samples_per_frame) as player:
                while self.should_run:
                    frames_ready = len(self.frame_deque)
                    if frames_ready:
                        self.output_latency = len(self.frame_deque)*self.frame_time
                        self.max_latency    = self.buffer_max_height*self.frame_time
                        self.underrun_at = None

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
                            else:
                                time.sleep(self.frame_time*0.1)

class PacketSink(RemoteSink):
    pass