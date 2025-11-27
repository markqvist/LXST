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
from LXST.Filters import BandPass, AGC


PRIMITIVE_NAME = "telephony"

class Profiles():
    BANDWIDTH_ULTRA_LOW     = 0x10
    BANDWIDTH_VERY_LOW   = 0x20
    BANDWIDTH_LOW         = 0x30
    QUALITY_MEDIUM        = 0x40
    QUALITY_HIGH          = 0x50
    QUALITY_MAX           = 0x60
    LATENCY_ULTRA_LOW     = 0x70
    LATENCY_LOW           = 0x80

    DEFAULT_PROFILE       = QUALITY_MEDIUM

    @staticmethod
    def available_profiles():
        return [Profiles.BANDWIDTH_ULTRA_LOW,
                Profiles.BANDWIDTH_VERY_LOW,
                Profiles.BANDWIDTH_LOW,
                Profiles.QUALITY_MEDIUM,
                Profiles.QUALITY_HIGH,
                Profiles.QUALITY_MAX,
                Profiles.LATENCY_LOW,
                Profiles.LATENCY_ULTRA_LOW]

    @staticmethod
    def profile_index(profile):
        if profile in Profiles.available_profiles():  return Profiles.available_profiles().index(profile)
        else:                                         return None

    @staticmethod
    def profile_name(profile):
        if   profile == Profiles.BANDWIDTH_ULTRA_LOW: return "Ultra Low Bandwidth"
        elif profile == Profiles.BANDWIDTH_VERY_LOW:  return "Very Low Bandwidth"
        elif profile == Profiles.BANDWIDTH_LOW:       return "Low Bandwidth"
        elif profile == Profiles.QUALITY_MEDIUM:      return "Medium Quality"
        elif profile == Profiles.QUALITY_HIGH:        return "High Quality"
        elif profile == Profiles.QUALITY_MAX:         return "Super High Quality"
        elif profile == Profiles.LATENCY_LOW:         return "Low Latency"
        elif profile == Profiles.LATENCY_ULTRA_LOW:   return "Ultra Low Latency"
        else:                                         return "Default"

    @staticmethod
    def profile_abbrevation(profile):
        if   profile == Profiles.BANDWIDTH_ULTRA_LOW: return "ULBW"
        elif profile == Profiles.BANDWIDTH_VERY_LOW:  return "VLBW"
        elif profile == Profiles.BANDWIDTH_LOW:       return "LBW"
        elif profile == Profiles.QUALITY_MEDIUM:      return "MQ"
        elif profile == Profiles.QUALITY_HIGH:        return "HQ"
        elif profile == Profiles.QUALITY_MAX:         return "SHQ"
        elif profile == Profiles.LATENCY_LOW:         return "LL"
        elif profile == Profiles.LATENCY_ULTRA_LOW:   return "ULL"
        else:                                         return "DFLT"

    @staticmethod
    def get_codec(profile):
        if   profile == Profiles.BANDWIDTH_ULTRA_LOW: return Codec2(mode=Codec2.CODEC2_700C)
        elif profile == Profiles.BANDWIDTH_VERY_LOW:  return Codec2(mode=Codec2.CODEC2_1600)
        elif profile == Profiles.BANDWIDTH_LOW:       return Codec2(mode=Codec2.CODEC2_3200)
        elif profile == Profiles.QUALITY_MEDIUM:      return Opus(profile=Opus.PROFILE_VOICE_MEDIUM)
        elif profile == Profiles.QUALITY_HIGH:        return Opus(profile=Opus.PROFILE_VOICE_HIGH)
        elif profile == Profiles.QUALITY_MAX:         return Opus(profile=Opus.PROFILE_VOICE_MAX)
        elif profile == Profiles.LATENCY_LOW:         return Opus(profile=Opus.PROFILE_VOICE_MEDIUM)
        elif profile == Profiles.LATENCY_ULTRA_LOW:   return Opus(profile=Opus.PROFILE_VOICE_MEDIUM)
        else:                                         return Opus(profile=Opus.PROFILE_VOICE_MEDIUM)

    @staticmethod
    def get_frame_time(profile):
        if   profile == Profiles.BANDWIDTH_ULTRA_LOW: return 400
        elif profile == Profiles.BANDWIDTH_VERY_LOW:  return 320
        elif profile == Profiles.BANDWIDTH_LOW:       return 200
        elif profile == Profiles.QUALITY_MEDIUM:      return 60
        elif profile == Profiles.QUALITY_HIGH:        return 60
        elif profile == Profiles.QUALITY_MAX:         return 60
        elif profile == Profiles.LATENCY_LOW:         return 20
        elif profile == Profiles.LATENCY_ULTRA_LOW:   return 10
        else:                                         return 60

    @staticmethod
    def next_profile(profile):
        profile_list = Profiles.available_profiles()
        if profile in profile_list:
            return profile_list[(Profiles.profile_index(profile)+1)%len(profile_list)]
        else: return None

class Signalling():
    STATUS_BUSY           = 0x00
    STATUS_REJECTED       = 0x01
    STATUS_CALLING        = 0x02
    STATUS_AVAILABLE      = 0x03
    STATUS_RINGING        = 0x04
    STATUS_CONNECTING     = 0x05
    STATUS_ESTABLISHED    = 0x06
    PREFERRED_PROFILE     = 0xFF
    AUTO_STATUS_CODES     = [STATUS_CALLING, STATUS_AVAILABLE, STATUS_RINGING,
                             STATUS_CONNECTING, STATUS_ESTABLISHED]

class Telephone(SignallingReceiver):
    RING_TIME             = 60
    WAIT_TIME             = 70
    CONNECT_TIME          = 5
    DIAL_TONE_FREQUENCY   = 382
    DIAL_TONE_EASE_MS     = 3.14159
    JOB_INTERVAL          = 5
    ANNOUNCE_INTERVAL_MIN = 60*5
    ANNOUNCE_INTERVAL     = 60*60*3
    ALLOW_ALL             = 0xFF
    ALLOW_NONE            = 0xFE

    @staticmethod
    def available_outputs(): return LXST.Sinks.Backend().all_speakers()
    
    @staticmethod
    def available_inputs(): return LXST.Sources.Backend().all_microphones()

    @staticmethod
    def default_output(): return LXST.Sinks.Backend().default_speaker()

    @staticmethod
    def default_input(): return LXST.Sources.Backend().default_microphone()

    def __init__(self, identity, ring_time=RING_TIME, wait_time=WAIT_TIME, auto_answer=None, allowed=ALLOW_ALL, receive_gain=0.0, transmit_gain=0.0):
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
        self.establishment_timeout = self.CONNECT_TIME
        self.links = {}
        self.ring_time = ring_time
        self.wait_time = wait_time
        self.auto_answer = auto_answer
        self.receive_gain = receive_gain
        self.transmit_gain = transmit_gain
        self.use_agc = True
        self.active_call = None
        self.call_status = Signalling.STATUS_AVAILABLE
        self._external_busy = False
        self.__ringing_callback = None
        self.__established_callback = None
        self.__ended_callback = None
        self.__busy_callback = None
        self.__rejected_callback = None
        self.target_frame_time_ms = None
        self.audio_output = None
        self.audio_input = None
        self.dial_tone = None
        self.dial_tone_frequency = self.DIAL_TONE_FREQUENCY
        self.dial_tone_ease_ms = self.DIAL_TONE_EASE_MS
        self.busy_tone_seconds = 4.25
        self.transmit_codec = None
        self.receive_codec = None
        self.receive_mixer = None
        self.transmit_mixer = None
        self.receive_pipeline = None
        self.transmit_pipeline = None
        self.__receive_muted = False
        self.__transmit_muted = False
        self.ringer_lock = threading.Lock()
        self.ringer_output = None
        self.ringer_pipeline = None
        self.ringtone_path = None
        self.speaker_device = None
        self.microphone_device = None
        self.ringer_device = None
        self.low_latency_output = False

        threading.Thread(target=self.__jobs, daemon=True).start()
        RNS.log(f"{self} listening on {RNS.prettyhexrep(self.destination.hash)}", RNS.LOG_DEBUG)

    def teardown(self):
        self.hangup()
        RNS.Transport.deregister_destination(self.destination)
        self.destination = None

    def announce(self, attached_interface=None):
        self.destination.announce(attached_interface=attached_interface)
        self.last_announce = time.time()

    def set_allowed(self, allowed):
        valid_allowed = [self.ALLOW_ALL, self.ALLOW_NONE]
        if callable(allowed) or type(allowed) == list or allowed in valid_allowed: self.allowed = allowed
        else: raise TypeError(f"Invalid type for allowed callers: {type(allowed)}")

    def set_blocked(self, blocked):
        if type(blocked) == list or blocked == None: self.blocked = blocked
        else: raise TypeError(f"Invalid type for blocked callers: {type(blocked)}")

    def set_connect_timeout(self, timeout):
        self.establishment_timeout = timeout

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

    def set_busy_callback(self, callback):
        if not callable(callback): raise TypeError(f"Invalid callback, {callback} is not callable")
        self.__busy_callback = callback

    def set_rejected_callback(self, callback):
        if not callable(callback): raise TypeError(f"Invalid callback, {callback} is not callable")
        self.__rejected_callback = callback

    def set_speaker(self, device):
        self.speaker_device = device
        RNS.log(f"{self} speaker device set to {device}", RNS.LOG_DEBUG)

    def set_microphone(self, device):
        self.microphone_device = device
        RNS.log(f"{self} microphone device set to {device}", RNS.LOG_DEBUG)

    def set_ringer(self, device):
        self.ringer_device = device
        RNS.log(f"{self} ringer device set to {device}", RNS.LOG_DEBUG)

    def set_ringtone(self, ringtone_path, gain=0.0):
        self.ringtone_path = ringtone_path
        self.ringtone_gain = gain
        RNS.log(f"{self} ringtone set to {self.ringtone_path}", RNS.LOG_DEBUG)

    def set_busy_tone_time(self, seconds=4.25):
        self.busy_tone_seconds = seconds

    def enable_agc(self, enable=True):
        if enable == True: self.use_agc = True
        else:              self.use_agc = False

    def disable_agc(self, disable=True):
        if disable == True: self.use_agc = False
        else:               self.use_agc = True

    def set_low_latency_output(self, enabled):
        if enabled:
            self.low_latency_output = True
            RNS.log(f"{self} low-latency output enabled", RNS.LOG_DEBUG)
        else:
            self.low_latency_output = False
            RNS.log(f"{self} low-latency output disabled", RNS.LOG_DEBUG)

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
            while time.time()<timeout and self.active_call == call: time.sleep(0.25)
            if self.active_call == call and self.call_status < Signalling.STATUS_ESTABLISHED:
                RNS.log(f"Ring timeout on call from {RNS.prettyhexrep(self.active_call.hash)}, hanging up", RNS.LOG_DEBUG)
                self.active_call.ring_timeout = True
                self.hangup()

        threading.Thread(target=job, daemon=True).start()

    def __timeout_outgoing_call_at(self, call, timeout):
        def job():
            while time.time()<timeout and self.active_call == call: time.sleep(0.25)
            if self.active_call == call and self.call_status < Signalling.STATUS_ESTABLISHED:
                RNS.log(f"Timeout on outgoing call to {RNS.prettyhexrep(self.active_call.hash)}, hanging up", RNS.LOG_DEBUG)
                self.hangup()

        threading.Thread(target=job, daemon=True).start()

    def __timeout_outgoing_establishment_at(self, call, timeout):
        def job():
            while time.time()<timeout and self.active_call == call: time.sleep(0.25)
            if self.active_call == call and self.call_status < Signalling.STATUS_RINGING:
                RNS.log(f"Timeout on outgoing connection establishment to {RNS.prettyhexrep(self.active_call.hash)}, hanging up", RNS.LOG_DEBUG)
                self.hangup()

        threading.Thread(target=job, daemon=True).start()

    def __incoming_link_established(self, link):
        link.is_incoming    = True
        link.is_outgoing    = False
        link.ring_timeout   = False
        link.answered       = False
        link.is_terminating = False
        link.profile        = None
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
                    self.handle_signalling_from(self.active_call)
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
            if not self.active_call.is_terminating: self.hangup()

    def set_busy(self, busy):
        self._external_busy = busy

    @property
    def busy(self):
        if self.call_status != Signalling.STATUS_AVAILABLE: return True
        else: return self._external_busy

    @property
    def active_profile(self):
        if not self.active_call: return None
        else:
            if not hasattr(self.active_call, "profile"): return None
            else:                                        return self.active_call.profile

    @property
    def receive_muted(self):
        if not self.active_call: return False
        else:
            if not self.receive_mixer: return False
            else: return self.receive_mixer.muted

    @property
    def transmit_muted(self):
        if not self.active_call: return False
        else:
            if not self.transmit_mixer: return False
            else: return self.transmit_mixer.muted
    
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
                self.active_call.answered = True
                self.__open_pipelines(identity)
                self.__start_pipelines()
                RNS.log(f"Call setup complete for {RNS.prettyhexrep(identity.hash)}", RNS.LOG_DEBUG)
                if callable(self.__established_callback): self.__established_callback(self.active_call.get_remote_identity())
                if self.low_latency_output: self.audio_output.enable_low_latency()
                return True

    def hangup(self, reason=None):
        if self.active_call:
            with self.call_handler_lock:
                terminating_call = self.active_call; self.active_call = None
                remote_identity = terminating_call.get_remote_identity()
                
                if terminating_call.is_incoming and self.call_status == Signalling.STATUS_RINGING:
                    if not terminating_call.ring_timeout and terminating_call.status == RNS.Link.ACTIVE:
                        self.signal(Signalling.STATUS_REJECTED, terminating_call)
                
                if terminating_call.status == RNS.Link.ACTIVE: terminating_call.teardown()
                self.__stop_pipelines()
                self.receive_mixer     = None
                self.transmit_mixer    = None
                self.receive_pipeline  = None
                self.transmit_pipeline = None
                self.audio_output      = None
                self.dial_tone         = None
                self.call_status       = Signalling.STATUS_AVAILABLE
                self.__receive_muted   = False
                self.__transmit_muted  = False
                if remote_identity: RNS.log(f"Call with {RNS.prettyhexrep(remote_identity.hash)} terminated", RNS.LOG_DEBUG)
                else: RNS.log(f"Outgoing call could not be connected, link establishment failed", RNS.LOG_DEBUG)
        
            if reason == None:
                if callable(self.__ended_callback):      self.__ended_callback(remote_identity)
            elif reason == Signalling.STATUS_BUSY:
                if   callable(self.__busy_callback):     self.__busy_callback(remote_identity)
                elif callable(self.__ended_callback):    self.__ended_callback(remote_identity)
            elif reason == Signalling.STATUS_REJECTED:
                if   callable(self.__rejected_callback): self.__rejected_callback(remote_identity)
                elif callable(self.__ended_callback):    self.__ended_callback(remote_identity)

    def mute_receive(self, mute=True):
        self.__receive_muted = mute
        if self.receive_mixer: self.receive_mixer.mute(mute)

    def unmute_receive(self, unmute=True):
        self.__receive_muted = not unmute
        if self.receive_mixer: self.receive_mixer.unmute(unmute)

    def mute_transmit(self, mute=True):
        self.__transmit_muted = mute
        if self.transmit_mixer: self.transmit_mixer.mute(mute)

    def unmute_transmit(self, unmute=True):
        self.__transmit_muted = not unmute
        if self.transmit_mixer: self.transmit_mixer.unmute(unmute)

    def set_receive_gain(self, gain=0.0):
        self.receive_gain = float(gain)
        if self.receive_mixer: self.receive_mixer.set_gain(self.receive_gain)

    def set_transmit_gain(self, gain=0.0):
        self.transmit_gain = float(gain)
        if self.transmit_mixer: self.transmit_mixer.set_gain(self.transmit_gain)

    def switch_profile(self, profile=None, from_signalling=False):
        if self.active_call:
            if self.active_call.profile == profile: return
            else:
                if self.call_status == Signalling.STATUS_ESTABLISHED:
                    self.active_call.profile = profile
                    self.transmit_codec = Profiles.get_codec(self.active_call.profile)
                    self.target_frame_time_ms = Profiles.get_frame_time(self.active_call.profile)
                    if not from_signalling: self.signal(Signalling.PREFERRED_PROFILE+self.active_call.profile, self.active_call)
                    self.__reconfigure_transmit_pipeline()

    def __select_call_profile(self, profile=None):
        if profile == None: profile = Profiles.DEFAULT_PROFILE
        self.active_call.profile = profile
        self.__select_call_codecs(self.active_call.profile)
        self.__select_call_frame_time(self.active_call.profile)
        RNS.log(f"Selected call profile 0x{RNS.hexrep(profile, delimit=False)}", RNS.LOG_DEBUG)

    def __select_call_codecs(self, profile=None):
        self.receive_codec = Null()
        self.transmit_codec = Profiles.get_codec(profile)

    def __select_call_frame_time(self, profile=None):
        self.target_frame_time_ms = Profiles.get_frame_time(profile)

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
        self.__select_call_profile(self.active_call.profile)
        if self.audio_output     == None: self.audio_output = LineSink(preferred_device=self.speaker_device)
        if self.receive_mixer    == None: self.receive_mixer = Mixer(target_frame_ms=self.target_frame_time_ms, gain=self.receive_gain)
        if self.dial_tone        == None: self.dial_tone = ToneSource(frequency=self.dial_tone_frequency, gain=0.0, ease_time_ms=self.dial_tone_ease_ms, target_frame_ms=self.target_frame_time_ms, codec=Null(), sink=self.receive_mixer)
        if self.receive_pipeline == None: self.receive_pipeline = Pipeline(source=self.receive_mixer, codec=Null(), sink=self.audio_output)

    def __activate_ring_tone(self):
        if self.ringtone_path != None and os.path.isfile(self.ringtone_path):
            if not self.ringer_pipeline:
                if not self.ringer_output: self.ringer_output = LineSink(preferred_device=self.ringer_device)
                self.ringer_source   = OpusFileSource(self.ringtone_path, loop=True, target_frame_ms=60)
                self.ringer_pipeline = Pipeline(source=self.ringer_source, codec=Null(), sink=self.ringer_output)

            def job():
                with self.ringer_lock:
                    while self.active_call and self.active_call.is_incoming and self.call_status == Signalling.STATUS_RINGING:
                        if not self.ringer_pipeline.running: self.ringer_pipeline.start()
                        time.sleep(0.1)
                    self.ringer_source.stop()
            threading.Thread(target=job, daemon=True).start()

    def __play_busy_tone(self):
        if self.busy_tone_seconds > 0:
            if self.audio_output == None or self.receive_mixer == None or self.dial_tone == None: self.__reset_dialling_pipelines()
            with self.pipeline_lock:
                window = 0.5; started = time.time()
                while time.time()-started < self.busy_tone_seconds:
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

    def __reconfigure_transmit_pipeline(self):
        if self.transmit_pipeline and self.call_status == Signalling.STATUS_ESTABLISHED:
            self.audio_input.stop()
            self.transmit_mixer.stop()
            self.transmit_pipeline.stop()
            self.transmit_mixer    =      Mixer(target_frame_ms=self.target_frame_time_ms, gain=self.transmit_gain)

            self.audio_input       = LineSource(preferred_device=self.microphone_device, target_frame_ms=self.target_frame_time_ms, codec=Raw(),
                                                sink=self.transmit_mixer, filters=self.active_call.filters, skip=0.075, ease_in=0.0)

            self.transmit_pipeline =   Pipeline(source=self.transmit_mixer, codec=self.transmit_codec, sink=self.active_call.packetizer)

            self.transmit_mixer.mute(self.__transmit_muted)
            self.transmit_mixer.start()
            self.audio_input.start()
            self.transmit_pipeline.start()

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

                    if self.use_agc: self.active_call.filters = [BandPass(250, 8500), AGC(target_level=-15.0)]
                    else:            self.active_call.filters = [BandPass(250, 8500)]

                    self.__prepare_dialling_pipelines()
                    self.active_call.packetizer = Packetizer(self.active_call, failure_callback=self.__packetizer_failure)

                    self.transmit_mixer    =      Mixer(target_frame_ms=self.target_frame_time_ms, gain=self.transmit_gain)

                    self.audio_input       = LineSource(preferred_device=self.microphone_device, target_frame_ms=self.target_frame_time_ms, codec=Raw(),
                                                        sink=self.transmit_mixer, filters=self.active_call.filters, skip=0.075, ease_in=0.225)

                    self.transmit_pipeline =   Pipeline(source=self.transmit_mixer, codec=self.transmit_codec, sink=self.active_call.packetizer)
                    
                    self.active_call.audio_source = LinkSource(link=self.active_call, signalling_receiver=self, sink=self.receive_mixer)
                    self.receive_mixer.set_source_max_frames(self.active_call.audio_source, 2)
                    
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

    def call(self, identity, profile=None):
        with self.call_handler_lock:
            if not self.active_call:
                self.call_status = Signalling.STATUS_CALLING
                outgoing_call_timeout = time.time()+self.wait_time
                outgoing_establishment_timeout = time.time()+self.establishment_timeout
                call_destination = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, APP_NAME, PRIMITIVE_NAME)
                if not RNS.Transport.has_path(call_destination.hash):
                    RNS.log(f"No path known for call to {RNS.prettyhexrep(call_destination.hash)}, requesting path...", RNS.LOG_DEBUG)
                    RNS.Transport.request_path(call_destination.hash)
                    while not RNS.Transport.has_path(call_destination.hash) and time.time() < outgoing_call_timeout: time.sleep(0.2)
                
                if not RNS.Transport.has_path(call_destination.hash) and time.time() >= outgoing_call_timeout: self.hangup()
                else:
                    RNS.log(f"Establishing link with {RNS.prettyhexrep(call_destination.hash)}...", RNS.LOG_DEBUG)
                    self.active_call = RNS.Link(call_destination,
                                                established_callback=self.__outgoing_link_established,
                                                closed_callback=self.__outgoing_link_closed)
                    
                    self.active_call.is_incoming    = False
                    self.active_call.is_outgoing    = True
                    self.active_call.is_terminating = False
                    self.active_call.ring_timeout   = False
                    self.active_call.profile        = profile
                    self.__timeout_outgoing_call_at(self.active_call, outgoing_call_timeout)
                    self.__timeout_outgoing_establishment_at(self.active_call, outgoing_establishment_timeout)

    def __outgoing_link_established(self, link):
        RNS.log(f"Link established for call with {link.get_remote_identity()}", RNS.LOG_DEBUG)
        link.set_link_closed_callback(self.__link_closed)
        self.handle_signalling_from(link)

    def __outgoing_link_closed(self, link):
        pass

    def signalling_received(self, signals, source):
        for signal in signals:
            if source != self.active_call: RNS.log("Received signalling on non-active call, ignoring", RNS.LOG_DEBUG)
            else:
                if self.active_call.is_incoming and not self.active_call.answered and signal < Signalling.PREFERRED_PROFILE:
                    return
                elif signal == Signalling.STATUS_BUSY:
                    RNS.log("Remote is busy, terminating", RNS.LOG_DEBUG)
                    self.active_call.is_terminating = True
                    self.__play_busy_tone()
                    self.__disable_dial_tone()
                    self.hangup(reason=Signalling.STATUS_BUSY)
                elif signal == Signalling.STATUS_REJECTED:
                    RNS.log("Remote rejected call, terminating", RNS.LOG_DEBUG)
                    self.__play_busy_tone()
                    self.__disable_dial_tone()
                    self.hangup(reason=Signalling.STATUS_REJECTED)
                elif signal == Signalling.STATUS_AVAILABLE:
                    RNS.log("Line available, sending identification", RNS.LOG_DEBUG)
                    self.call_status = signal
                    source.identify(self.identity)
                elif signal == Signalling.STATUS_RINGING:
                    RNS.log("Identification accepted, remote is now ringing", RNS.LOG_DEBUG)
                    self.call_status = signal
                    self.__prepare_dialling_pipelines()
                    self.signal(Signalling.PREFERRED_PROFILE+self.active_call.profile, self.active_call)
                    if self.active_call and self.active_call.is_outgoing: self.__activate_dial_tone()
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
                        if self.low_latency_output: self.audio_output.enable_low_latency()
                elif signal >= Signalling.PREFERRED_PROFILE:
                    profile = signal - Signalling.PREFERRED_PROFILE
                    if self.active_call and self.call_status == Signalling.STATUS_ESTABLISHED: self.switch_profile(profile, from_signalling=True)
                    else:                                                                      self.__select_call_profile(profile)

    def __str__(self):
        return f"<lxst.telephony/{RNS.hexrep(self.identity.hash, delimit=False)}>"