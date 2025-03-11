import os
import RNS
import LXST
import time
import threading

from LXST import APP_NAME
from LXST import Mixer, Pipeline
from LXST.Codecs import Raw, Opus, Codec2, Null
from LXST.Sinks import LineSink
from LXST.Sources import LineSource, OpusFileSource
from LXST.Generators import ToneSource
from LXST.Network import SignallingReceiver, Packetizer, LinkSource

PRIMITIVE_NAME = "telephony"

class Signalling():
    STATUS_BUSY           = 0x00
    STATUS_REJECTED       = 0x01
    STATUS_CALLING        = 0x02
    STATUS_AVAILABLE      = 0x03
    STATUS_RINGING        = 0x04
    STATUS_CONNECTING     = 0x05
    STATUS_ESTABLISHED    = 0x06
    AUTO_STATUS_CODES     = [STATUS_CALLING, STATUS_AVAILABLE, STATUS_RINGING,
                          STATUS_CONNECTING, STATUS_ESTABLISHED]

class Telephone(SignallingReceiver):
    RING_TIME             = 60
    WAIT_TIME             = 70
    DIAL_TONE_FREQUENCY   = 382
    DIAL_TONE_EASE_MS     = 3.14159
    JOB_INTERVAL          = 5
    ANNOUNCE_INTERVAL_MIN = 60*5
    ANNOUNCE_INTERVAL     = 60*60*3
    ALLOW_ALL             = 0xFF
    ALLOW_NONE            = 0xFE

    def __init__(self, identity, ring_time=RING_TIME, wait_time=WAIT_TIME, auto_answer=None, allowed=ALLOW_ALL):
        super().__init__()
        self.identity = identity
        self.destination = RNS.Destination(self.identity, RNS.Destination.IN, RNS.Destination.SINGLE, APP_NAME, PRIMITIVE_NAME)
        self.destination.set_proof_strategy(RNS.Destination.PROVE_NONE)
        self.destination.set_link_established_callback(self.__incoming_link_established)
        self.allowed = allowed
        self.blocked = None
        self.last_announce = 0
        self.call_handler_lock = threading.Lock()
        self.pipeline_lock = threading.Lock()
        self.caller_pipeline_open_lock = threading.Lock()
        self.links = {}
        self.ring_time = ring_time
        self.wait_time = wait_time
        self.auto_answer = auto_answer
        self.active_call = None
        self.call_status = Signalling.STATUS_AVAILABLE
        self._external_busy = False
        self.__ringing_callback = None
        self.__established_callback = None
        self.__ended_callback = None
        self.target_frame_time_ms = None
        self.audio_output = None
        self.audio_input = None
        self.dial_tone = None
        self.dial_tone_frequency = self.DIAL_TONE_FREQUENCY
        self.dial_tone_ease_ms = self.DIAL_TONE_EASE_MS
        self.transmit_codec = None
        self.receive_codec = None
        self.receive_mixer = None
        self.transmit_mixer = None
        self.receive_pipeline = None
        self.transmit_pipeline = None
        self.ringer_lock = threading.Lock()
        self.ringer_output = None
        self.ringer_pipeline = None
        self.ringtone_path = None
        self.speaker_device = None
        self.microphone_device = None
        self.ringer_device = None

        threading.Thread(target=self.__jobs, daemon=True).start()
        RNS.log(f"{self} listening on {RNS.prettyhexrep(self.destination.hash)}", RNS.LOG_DEBUG)

    def teardown(self):
        self.hangup()
        RNS.Transport.deregister_destination(self.destination)
        self.destination = None

    def announce(self):
        self.destination.announce()
        self.last_announce = time.time()

    def set_allowed(self, allowed):
        valid_allowed = [self.ALLOW_ALL, self.ALLOW_NONE]
        if callable(allowed) or type(allowed) == list or allowed in valid_allowed: self.allowed = allowed
        else: raise TypeError(f"Invalid type for allowed callers: {type(allowed)}")

    def set_blocked(self, blocked):
        if type(blocked) == list or blocked == None: self.blocked = blocked
        else: raise TypeError(f"Invalid type for blocked callers: {type(blocked)}")

    def set_announce_interval(self, announce_interval):
        if not type(announce_interval) == int: raise TypeError(f"Invalid type for announce interval: {announce_interval}")
        else:
            if announce_interval < self.ANNOUNCE_INTERVAL_MIN: announce_interval = self.ANNOUNCE_INTERVAL_MIN
            self.announce_interval = announce_interval

    def set_ringing_callback(self, callback):
        if not callable(callback): raise TypeError(f"Invalid callback, {callback} is not callable")
        self.__ringing_callback = callback

    def set_established_callback(self, callback):
        if not callable(callback): raise TypeError(f"Invalid callback, {callback} is not callable")
        self.__established_callback = callback

    def set_ended_callback(self, callback):
        if not callable(callback): raise TypeError(f"Invalid callback, {callback} is not callable")
        self.__ended_callback = callback

    def set_speaker(self, device):
        self.speaker_device = device
        RNS.log(f"{self} speaker device set to {device}", RNS.LOG_DEBUG)

    def set_microphone(self, device):
        self.microphone_device = device
        RNS.log(f"{self} microphone device set to {device}", RNS.LOG_DEBUG)

    def set_ringer(self, device):
        self.ringer_device = device
        RNS.log(f"{self} ringer device set to {device}", RNS.LOG_DEBUG)

    def set_ringtone(self, ringtone_path, gain=1.0):
        self.ringtone_path = ringtone_path
        self.ringtone_gain = gain
        RNS.log(f"{self} ringtone set to {self.ringtone_path}", RNS.LOG_DEBUG)

    def __jobs(self):
        while self.destination != None:
            time.sleep(self.JOB_INTERVAL)
            if time.time() > self.last_announce+self.ANNOUNCE_INTERVAL:
                if self.destination != None: self.announce()

    def __is_allowed(self, remote_identity):
        identity_hash = remote_identity.hash
        if   type(self.blocked) == list and identity_hash in self.blocked: return False
        elif self.allowed == self.ALLOW_ALL: return True
        elif self.allowed == self.ALLOW_NONE: return False
        elif type(self.allowed) == list: return identity_hash in self.allowed
        elif callable(self.allowed): return self.allowed(identity_hash)

    def __timeout_incoming_call_at(self, call, timeout):
        def job():
            while time.time()<timeout and self.active_call == call:
                time.sleep(0.25)

            if self.active_call == call and self.call_status < Signalling.STATUS_ESTABLISHED:
                RNS.log(f"Ring timeout on call from {RNS.prettyhexrep(self.active_call.hash)}, hanging up", RNS.LOG_DEBUG)
                self.active_call.ring_timeout = True
                self.hangup()

        threading.Thread(target=job, daemon=True).start()

    def __timeout_outgoing_call_at(self, call, timeout):
        def job():
            while time.time()<timeout and self.active_call == call:
                time.sleep(0.25)

            if self.active_call == call and self.call_status < Signalling.STATUS_ESTABLISHED:
                RNS.log(f"Timeout on outgoing call to {RNS.prettyhexrep(self.active_call.hash)}, hanging up", RNS.LOG_DEBUG)
                self.hangup()

        threading.Thread(target=job, daemon=True).start()

    def __incoming_link_established(self, link):
        link.is_incoming  = True
        link.is_outgoing  = False
        link.ring_timeout = False
        with self.call_handler_lock:
            if self.active_call or self.busy:
                RNS.log(f"Incoming call, but line is already active, signalling busy", RNS.LOG_DEBUG)
                self.signal(Signalling.STATUS_BUSY, link)
                link.teardown()
            else:
                link.set_remote_identified_callback(self.__caller_identified)
                link.set_link_closed_callback(self.__link_closed)
                self.links[link.link_id] = link
                self.signal(Signalling.STATUS_AVAILABLE, link)

    def __caller_identified(self, link, identity):
        with self.call_handler_lock:
            if self.active_call or self.busy:
                RNS.log(f"Caller identified as {RNS.prettyhexrep(identity.hash)}, but line is already active, signalling busy", RNS.LOG_DEBUG)
                self.signal(Signalling.STATUS_BUSY, link)
                link.teardown()
            else:
                if not self.__is_allowed(identity):
                    RNS.log(f"Identified caller {RNS.prettyhexrep(identity.hash)} was not allowed, signalling busy", RNS.LOG_DEBUG)
                    self.signal(Signalling.STATUS_BUSY, link)
                    link.teardown()

                else:
                    RNS.log(f"Caller identified as {RNS.prettyhexrep(identity.hash)}, ringing", RNS.LOG_DEBUG)
                    self.active_call = link
                    self.__reset_dialling_pipelines()
                    self.signal(Signalling.STATUS_RINGING, self.active_call)
                    self.__activate_ring_tone()
                    if callable(self.__ringing_callback): self.__ringing_callback(identity)
                    if self.auto_answer:
                        def cb():
                            RNS.log(f"Auto-answering call from {RNS.prettyhexrep(identity.hash)} in {RNS.prettytime(self.auto_answer)}", RNS.LOG_DEBUG)
                            time.sleep(self.auto_answer)
                            self.answer(identity)
                        threading.Thread(target=cb, daemon=True).start()
                    
                    else:
                        self.__timeout_incoming_call_at(self.active_call, time.time()+self.ring_time)

    def __link_closed(self, link):
        if link == self.active_call:
            RNS.log(f"Remote for {RNS.prettyhexrep(link.get_remote_identity().hash)} hung up", RNS.LOG_DEBUG)
            self.hangup()

    def set_busy(self, busy):
        self._external_busy = busy

    @property
    def busy(self):
        if self.call_status != Signalling.STATUS_AVAILABLE:
            return True
        else:
            return self._external_busy
    
    def signal(self, signal, link):
        if signal in Signalling.AUTO_STATUS_CODES: self.call_status = signal
        super().signal(signal, link)

    def answer(self, identity):
        with self.call_handler_lock:
            if self.active_call and self.active_call.get_remote_identity() == identity and self.call_status > Signalling.STATUS_RINGING:
                RNS.log(f"Incoming call from {RNS.prettyhexrep(identity.hash)} already answered and active")
                return False
            elif not self.active_call:
                RNS.log(f"Answering call failed, no active incoming call", RNS.LOG_ERROR)
                return False
            elif not self.active_call.get_remote_identity():
                RNS.log(f"Answering call failed, active incoming call is not from {RNS.prettyhexrep(identity.hash)}", RNS.LOG_ERROR)
                return False
            else:
                RNS.log(f"Answering call from {RNS.prettyhexrep(identity.hash)}", RNS.LOG_DEBUG)
                self.__open_pipelines(identity)
                self.__start_pipelines()
                RNS.log(f"Call setup complete for {RNS.prettyhexrep(identity.hash)}", RNS.LOG_DEBUG)
                if callable(self.__established_callback): self.__established_callback(self.active_call.get_remote_identity())
                return True

    def hangup(self):
        if self.active_call:
            with self.call_handler_lock:
                terminating_call = self.active_call; self.active_call = None
                remote_identity = terminating_call.get_remote_identity()
                
                if terminating_call.is_incoming and self.call_status == Signalling.STATUS_RINGING:
                    if not terminating_call.ring_timeout and terminating_call.status == RNS.Link.ACTIVE:
                        self.signal(Signalling.STATUS_REJECTED, terminating_call)
                
                if terminating_call.status == RNS.Link.ACTIVE: terminating_call.teardown()
                self.__stop_pipelines()
                self.receive_mixer = None
                self.transmit_mixer = None
                self.receive_pipeline = None
                self.transmit_pipeline = None
                self.audio_output = None
                self.dial_tone = None
                self.call_status = Signalling.STATUS_AVAILABLE
                if remote_identity:
                    RNS.log(f"Call with {RNS.prettyhexrep(remote_identity.hash)} terminated", RNS.LOG_DEBUG)
                else:
                    RNS.log(f"Outgoing call could not be connected, link establishment failed", RNS.LOG_DEBUG)
        
            if callable(self.__ended_callback): self.__ended_callback(remote_identity)

    def mute_receive(self):
        pass

    def mute_transmit(self):
        pass

    def select_call_codecs(self):
        self.receive_codec = Null()
        
        # self.transmit_codec = Codec2(mode=Codec2.CODEC2_700C)
        # self.transmit_codec = Codec2(mode=Codec2.CODEC2_1600)
        # self.transmit_codec = Codec2(mode=Codec2.CODEC2_3200)
        # self.transmit_codec = Opus(profile=Opus.PROFILE_VOICE_LOW)
        self.transmit_codec = Opus(profile=Opus.PROFILE_VOICE_MEDIUM)
        # self.transmit_codec = Opus(profile=Opus.PROFILE_VOICE_HIGH)
        # self.transmit_codec = Opus(profile=Opus.PROFILE_VOICE_MAX)
        # self.transmit_codec = Opus(profile=Opus.PROFILE_AUDIO_MIN)
        # self.transmit_codec = Opus(profile=Opus.PROFILE_AUDIO_LOW)
        # self.transmit_codec = Opus(profile=Opus.PROFILE_AUDIO_MEDIUM)
        # self.transmit_codec = Opus(profile=Opus.PROFILE_AUDIO_HIGH)
        # self.transmit_codec = Opus(profile=Opus.PROFILE_AUDIO_MAX)
        # self.transmit_codec = Raw()

    def select_call_frame_time(self):
        self.target_frame_time_ms = 60
        return self.target_frame_time_ms

    def __reset_dialling_pipelines(self):
        with self.pipeline_lock:
            if self.audio_output: self.audio_output.stop()
            if self.dial_tone: self.dial_tone.stop()
            if self.receive_pipeline: self.receive_pipeline.stop()
            if self.receive_mixer: self.receive_mixer.stop()
            self.audio_output = None
            self.dial_tone = None
            self.receive_pipeline = None
            self.receive_mixer = None
            self.__prepare_dialling_pipelines()

    def __prepare_dialling_pipelines(self):
        self.select_call_frame_time()
        self.select_call_codecs()
        if self.audio_output == None:     self.audio_output = LineSink(preferred_device=self.speaker_device)
        if self.receive_mixer == None:    self.receive_mixer = Mixer(target_frame_ms=self.target_frame_time_ms)
        if self.dial_tone == None:        self.dial_tone = ToneSource(frequency=self.dial_tone_frequency, gain=0.0, ease_time_ms=self.dial_tone_ease_ms, target_frame_ms=self.target_frame_time_ms, codec=Null(), sink=self.receive_mixer)
        if self.receive_pipeline == None: self.receive_pipeline = Pipeline(source=self.receive_mixer, codec=Null(), sink=self.audio_output)

    def __activate_ring_tone(self):
        if self.ringtone_path != None and os.path.isfile(self.ringtone_path):
            if not self.ringer_pipeline:
                if not self.ringer_output: self.ringer_output = LineSink(preferred_device=self.ringer_device)
                self.ringer_source = OpusFileSource(self.ringtone_path, loop=True, target_frame_ms=60)
                self.ringer_pipeline = Pipeline(source=self.ringer_source, codec=Null(), sink=self.ringer_output)

            def job():
                with self.ringer_lock:
                    while self.active_call and self.active_call.is_incoming and self.call_status == Signalling.STATUS_RINGING:
                        if not self.ringer_pipeline.running: self.ringer_pipeline.start()
                        time.sleep(0.1)
                    self.ringer_source.stop()
            threading.Thread(target=job, daemon=True).start()

    def __play_busy_tone(self):
        if self.audio_output == None or self.receive_mixer == None or self.dial_tone == None: self.__reset_dialling_pipelines()
        with self.pipeline_lock:
            window = 0.5; started = time.time()
            while time.time()-started < 4.25:
                elapsed = (time.time()-started)%window
                if elapsed > 0.25: self.__enable_dial_tone()
                else: self.__mute_dial_tone()
                time.sleep(0.005)
            time.sleep(0.5)

    def __activate_dial_tone(self):
        def job():
            window = 7
            started = time.time()
            while self.active_call and self.active_call.is_outgoing and self.call_status == Signalling.STATUS_RINGING:
                elapsed = (time.time()-started)%window
                if elapsed > 0.05 and elapsed < 2.05: self.__enable_dial_tone()
                else: self.__mute_dial_tone()
                time.sleep(0.2)

        threading.Thread(target=job, daemon=True).start()

    def __enable_dial_tone(self):
        if not self.receive_mixer.should_run: self.receive_mixer.start()
        self.dial_tone.gain = 0.04
        if not self.dial_tone.running: self.dial_tone.start()

    def __mute_dial_tone(self):
        if not self.receive_mixer.should_run: self.receive_mixer.start()
        if self.dial_tone.running and self.dial_tone.gain != 0: self.dial_tone.gain = 0.0
        if not self.dial_tone.running: self.dial_tone.start()
    
    def __disable_dial_tone(self):
        if self.dial_tone and self.dial_tone.running:
            self.dial_tone.stop()

    def __open_pipelines(self, identity):
        with self.pipeline_lock:
            if not self.active_call.get_remote_identity() == identity:
                RNS.log("Identity mismatch while opening call pipelines, tearing down call", RNS.LOG_ERROR)
                self.hangup()
            else:
                if not hasattr(self.active_call, "pipelines_opened"): self.active_call.pipelines_opened = False
                if self.active_call.pipelines_opened: RNS.log(f"Pipelines already openened for call with {RNS.prettyhexrep(identity.hash)}", RNS.LOG_ERROR)
                else:
                    RNS.log(f"Opening audio pipelines for call with {RNS.prettyhexrep(identity.hash)}", RNS.LOG_DEBUG)
                    if self.active_call.is_incoming: self.signal(Signalling.STATUS_CONNECTING, self.active_call)

                    self.__prepare_dialling_pipelines()
                    self.transmit_mixer = Mixer(target_frame_ms=self.target_frame_time_ms)
                    self.audio_input = LineSource(preferred_device=self.microphone_device, target_frame_ms=self.target_frame_time_ms, codec=Raw(), sink=self.transmit_mixer)
                    # self.audio_input = OpusFileSource("/home/markqvist/Information/Source/LXST/docs/425.opus", loop=True, target_frame_ms=self.target_frame_time_ms, codec=Raw(), sink=self.transmit_mixer, timed=True)
                    self.transmit_pipeline = Pipeline(source=self.transmit_mixer,
                                                      codec=self.transmit_codec,
                                                      sink=Packetizer(self.active_call, failure_callback=self.__packetizer_failure))
                    
                    self.active_call.audio_source = LinkSource(link=self.active_call, signalling_receiver=self, sink=self.receive_mixer)
                    
                    self.signal(Signalling.STATUS_ESTABLISHED, self.active_call)

    def __packetizer_failure(self):
        RNS.log(f"Frame packetization failed, terminating call", RNS.LOG_ERROR)
        self.hangup()

    def __start_pipelines(self):
        with self.pipeline_lock:
            if self.receive_mixer:     self.receive_mixer.start()
            if self.transmit_mixer:    self.transmit_mixer.start()
            if self.audio_input:       self.audio_input.start()
            if self.transmit_pipeline: self.transmit_pipeline.start()
            if not self.audio_input:   RNS.log("No audio input was ready at call establishment", RNS.LOG_ERROR)
            RNS.log(f"Audio pipelines started", RNS.LOG_DEBUG)

    def __stop_pipelines(self):
        with self.pipeline_lock:
            if self.receive_mixer:     self.receive_mixer.stop()
            if self.transmit_mixer:    self.transmit_mixer.stop()
            if self.audio_input:       self.audio_input.stop()
            if self.receive_pipeline:  self.receive_pipeline.stop()
            if self.transmit_pipeline: self.transmit_pipeline.stop()
            RNS.log(f"Audio pipelines stopped", RNS.LOG_DEBUG)

    def call(self, identity):
        with self.call_handler_lock:
            if not self.active_call:
                self.call_status = Signalling.STATUS_CALLING
                outgoing_call_timeout = time.time()+self.wait_time
                call_destination = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, APP_NAME, PRIMITIVE_NAME)
                if not RNS.Transport.has_path(call_destination.hash):
                    RNS.log(f"No path known for call to {RNS.prettyhexrep(call_destination.hash)}, requesting path...", RNS.LOG_DEBUG)
                    RNS.Transport.request_path(call_destination.hash)
                    while not RNS.Transport.has_path(call_destination.hash) and time.time() < outgoing_call_timeout: time.sleep(0.2)
                
                if not RNS.Transport.has_path(call_destination.hash) and time.time() >= outgoing_call_timeout:
                    self.hangup()
                else:
                    RNS.log(f"Establishing link with {RNS.prettyhexrep(call_destination.hash)}...", RNS.LOG_DEBUG)
                    self.active_call = RNS.Link(call_destination,
                                                established_callback=self.__outgoing_link_established,
                                                closed_callback=self.__outgoing_link_closed)
                    
                    self.active_call.is_incoming  = False
                    self.active_call.is_outgoing  = True
                    self.active_call.ring_timeout = False
                    self.__timeout_outgoing_call_at(self.active_call, outgoing_call_timeout)

    def __outgoing_link_established(self, link):
        RNS.log(f"Link established for call with {link.get_remote_identity()}", RNS.LOG_DEBUG)
        link.set_link_closed_callback(self.__link_closed)
        self.handle_signalling_from(link)

    def __outgoing_link_closed(self, link):
        pass

    def signalling_received(self, signals, source):
        for signal in signals:
            if source != self.active_call:
                RNS.log("Received signalling on non-active call, ignoring", RNS.LOG_DEBUG)
            else:
                if signal == Signalling.STATUS_BUSY:
                    RNS.log("Remote is busy, terminating", RNS.LOG_DEBUG)
                    self.__play_busy_tone()
                    self.__disable_dial_tone()
                    self.hangup()
                elif signal == Signalling.STATUS_REJECTED:
                    RNS.log("Remote rejected call, terminating", RNS.LOG_DEBUG)
                    self.__play_busy_tone()
                    self.__disable_dial_tone()
                    self.hangup()
                elif signal == Signalling.STATUS_AVAILABLE:
                    RNS.log("Line available, sending identification", RNS.LOG_DEBUG)
                    self.call_status = signal
                    source.identify(self.identity)
                elif signal == Signalling.STATUS_RINGING:
                    RNS.log("Identification accepted, remote is now ringing", RNS.LOG_DEBUG)
                    self.call_status = signal
                    self.__prepare_dialling_pipelines()
                    if self.active_call and self.active_call.is_outgoing:
                        self.__activate_dial_tone()
                elif signal == Signalling.STATUS_CONNECTING:
                    RNS.log("Call answered, remote is performing call setup, opening audio pipelines", RNS.LOG_DEBUG)
                    self.call_status = signal
                    with self.caller_pipeline_open_lock:
                        self.__reset_dialling_pipelines()
                        self.__open_pipelines(self.active_call.get_remote_identity())
                elif signal == Signalling.STATUS_ESTABLISHED:
                    if self.active_call and self.active_call.is_outgoing:
                        RNS.log("Remote call setup completed, starting audio pipelines", RNS.LOG_DEBUG)
                        with self.caller_pipeline_open_lock:
                            self.__start_pipelines()
                            self.__disable_dial_tone()
                        RNS.log(f"Call setup complete for {RNS.prettyhexrep(self.active_call.get_remote_identity().hash)}", RNS.LOG_DEBUG)
                        self.call_status = signal
                        if callable(self.__established_callback): self.__established_callback(self.active_call.get_remote_identity())

    def __str__(self):
        return f"<lxst.telephony/{RNS.hexrep(self.identity.hash, delimit=False)}>"