# Reticulum License
#
# Copyright (c) 2025 Mark Qvist
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# - The Software shall not be used in any kind of system which includes amongst
#   its functions the ability to purposefully do harm to human beings.
#
# - The Software shall not be used, directly or indirectly, in the creation of
#   an artificial intelligence, machine learning or language model training
#   dataset, including but not limited to any use that contributes to the
#   training or development of such a model or algorithm.
#
# - The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import atexit
import collections.abc
import time
import re
import threading
import numpy
import RNS

if RNS.vendor.platformutils.get_platform() == "android":
    try: from jnius import autoclass, cast
    except Exception as e:
        RNS.log(f"Could load module for native Java interface access on Android: {e}")
        raise e

class _AndroidAudio:
    COMMUNICATION_MODE_TYPES = ["Internal Earpiece",
                                "Bluetooth SCO",
                                "BLE Headset",
                                "Hearing Aid",
                                "Wired Headphones",
                                "Wired Headset"]

    IGNORED_DEVICE_TYPES     = ["Telephony",
                                "Remote Submix"]

    ADD_VIRT_RINGER_TYPES    = ["Internal Speaker"]

    DEFAULT_SINK             =  "Internal Speaker"
    FALLBACK_SINKS           = ["Internal Speaker",
                                "Ringer Speaker",
                                "Hearing Aid",
                                "Wired Headset",
                                "USB Headset",
                                "BLE Headset",
                                "Bluetooth SCO",
                                "BLE Speaker",
                                "Bluetooth A2DP",
                                "Wired Headphones",
                                "Analog Line",
                                "Digital Line",
                                "USB Device",
                                "USB Accessory",
                                "HDMI"]
    
    DEFAULT_SOURCE           =  "Internal Microphone"
    FALLBACK_SOURCES         = ["Internal Microphone",
                                "Hearing Aid",
                                "Wired Headset",
                                "USB Headset",
                                "BLE Headset",
                                "Bluetooth SCO",
                                "Analog Line",
                                "Digital Line",
                                "USB Device",
                                "USB Accessory"]

    VIRTUAL_DEVICE_OFFSET    = 0xFFFF

    def __init__(self):
        self._client_name = None
        self.available_devices = []
        self.android_api_version = None
        try:
            self.android_api_version = autoclass('android.os.Build$VERSION').SDK_INT
            Context  = autoclass('android.content.Context')
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            
            if activity == None:
                RNS.log(f"Could not obtain application context, instance may be running in a service context.", RNS.LOG_DEBUG)
                android_service = autoclass('org.kivy.android.PythonService').mService
                activity        = android_service.getApplication().getApplicationContext()
                if activity    != None: RNS.log(f"Successfully obtained application context from service", RNS.LOG_DEBUG)

            if activity == None:
                RNS.log(f"Failed to obtain application context for audio stream acquisition", RNS.LOG_ERROR)
                raise ValueError("No application context available for audio stream acquisition")

            self.AudioManager        = activity.getSystemService(autoclass("android.media.AudioManager"))
            self.AudioDeviceInfo     = autoclass("android.media.AudioDeviceInfo")
            adi                      = self.AudioDeviceInfo

            # Populate device type descriptions from JNI
            self.device_type_descriptions = {
                adi.TYPE_AUX_LINE: "Aux Line",                  # 0x13 - API level 23
                adi.TYPE_BLUETOOTH_A2DP: "Bluetooth A2DP",      # 0x08 - API level 23
                adi.TYPE_BLUETOOTH_SCO: "Bluetooth SCO",        # 0x07 - API level 23
                adi.TYPE_BUILTIN_EARPIECE: "Internal Earpiece", # 0x01 - API level 23
                adi.TYPE_BUILTIN_MIC: "Internal Microphone",    # 0x0f - API level 23
                adi.TYPE_BUILTIN_SPEAKER: "Internal Speaker",   # 0x02 - API level 23
                adi.TYPE_DOCK: "Dock",                          # 0x0d - API level 23
                adi.TYPE_FM: "FM",                              # 0x0e - API level 23
                adi.TYPE_FM_TUNER: "FM Tuner",                  # 0x10 - API level 23
                adi.TYPE_HDMI: "HDMI",                          # 0x09 - API level 23
                adi.TYPE_HDMI_ARC: "HDMI ARC",                  # 0x0a - API level 23
                adi.TYPE_IP: "IP",                              # 0x14 - API level 23
                adi.TYPE_LINE_ANALOG: "Analog Line",            # 0x05 - API level 23
                adi.TYPE_LINE_DIGITAL: "Digital Line",          # 0x06 - API level 23
                adi.TYPE_TELEPHONY: "Telephony",                # 0x12 - API level 23
                adi.TYPE_TV_TUNER: "TV Tuner",                  # 0x11 - API level 23
                adi.TYPE_UNKNOWN: "Unknown",                    # 0x00 - API level 23
                adi.TYPE_USB_ACCESSORY: "USB Accessory",        # 0x0c - API level 23
                adi.TYPE_USB_DEVICE: "USB Device",              # 0x0b - API level 23
                adi.TYPE_WIRED_HEADPHONES: "Wired Headphones",  # 0x04 - API level 23
                adi.TYPE_WIRED_HEADSET: "Wired Headset",        # 0x03 - API level 23
                adi.TYPE_BUS: "Bus",                            # 0x15 - API level 24
            }

            if self.android_api_version >= 26:
                self.device_type_descriptions[adi.TYPE_USB_HEADSET] = "USB Headset" # 0x16 - API level 26

            if self.android_api_version >= 28:
                self.device_type_descriptions[adi.TYPE_HEARING_AID] = "Hearing Aid" # 0x17 - API level 28

            if self.android_api_version >= 30:
                self.device_type_descriptions[adi.TYPE_BUILTIN_SPEAKER_SAFE] = "Ringer Speaker" # 0x18 - API level 30

            if self.android_api_version >= 31:
                self.device_type_descriptions[adi.TYPE_BLE_HEADSET] = "BLE Headset"     # 0x1a - API level 31
                self.device_type_descriptions[adi.TYPE_BLE_SPEAKER] = "BLE Speaker"     # 0x1b - API level 31
                self.device_type_descriptions[adi.TYPE_HDMI_EARC] = "HDMI EARC"         # 0x1d - API level 31
                self.device_type_descriptions[adi.TYPE_REMOTE_SUBMIX] = "Remote Submix" # 0x19 - API level 31

            if self.android_api_version >= 33:
                self.device_type_descriptions[adi.TYPE_BLE_BROADCAST] = "BLE Broadcast" # 0x1e - API level 33
                
            if self.android_api_version >= 34:
                self.device_type_descriptions[adi.TYPE_DOCK_ANALOG] = "Analog Dock" # 0x1f - API level 34
            
            if self.android_api_version >= 36:
                self.device_type_descriptions[adi.TYPE_MULTICHANNEL_GROUP] = "Multichannel Group" # 0x20 - API level 36

            added_ids = []
            found_ringer = False
            virtual_ringers = []
            if self.android_api_version < 31: available_devices = []
            else:                             available_devices = self.AudioManager.getAvailableCommunicationDevices()
            for device in available_devices:
                try:
                    device_id = device.getId(); device_type = device.getType(); channel_counts = device.getChannelCounts()
                    if len(channel_counts) == 0: channel_counts = [1, 2]
                    if not device_id in added_ids:
                        if 1 in channel_counts or 2 in channel_counts:
                            type_description = self.device_type_descriptions[device_type] if device_type in self.device_type_descriptions else "Unrecognized"
                            if not type_description in self.IGNORED_DEVICE_TYPES:
                                d = {"id": device_id, "name": device.getProductName(), "type": device_type, "type_description": type_description, "channel_counts": channel_counts,
                                     "is_source": device.isSource(), "is_sink": device.isSink(), "is_comms": True, "is_virtual": False}
                                added_ids.append(device_id)
                                self.available_devices.append(d)

                                if type_description == "Ringer Speaker": found_ringer = True
                                if type_description in self.ADD_VIRT_RINGER_TYPES:
                                    d = {"id": device_id+self.VIRTUAL_DEVICE_OFFSET, "name": device.getProductName(), "type": device_type, "type_description": "Ringer Speaker",
                                          "channel_counts": channel_counts, "is_source": device.isSource(), "is_sink": device.isSink(), "is_comms": False, "is_virtual": True}
                                    virtual_ringers.append(d)
                
                except Exception as e:
                    RNS.log(f"An error occurred while mapping available communications devices: {e}", RNS.LOG_ERROR)
                    RNS.trace_exception(e)

            available_devices = self.AudioManager.getDevices(self.AudioManager.GET_DEVICES_ALL)
            for device in available_devices:
                try:
                    device_id = device.getId(); device_type = device.getType(); channel_counts = device.getChannelCounts()
                    if len(channel_counts) == 0: channel_counts = [1, 2]
                    if not device_id in added_ids:
                        if 1 in channel_counts or 2 in channel_counts:
                            type_description = self.device_type_descriptions[device_type] if device_type in self.device_type_descriptions else "Unrecognized"
                            if not type_description in self.IGNORED_DEVICE_TYPES:
                                d = {"id": device_id, "name": device.getProductName(), "type": device_type, "type_description": type_description, "channel_counts": channel_counts,
                                     "is_source": device.isSource(), "is_sink": device.isSink(), "is_comms": False, "is_virtual": False}
                                added_ids.append(device_id)
                                self.available_devices.append(d)

                                if type_description == "Ringer Speaker": found_ringer = True
                                if type_description in self.ADD_VIRT_RINGER_TYPES:
                                    d = {"id": device_id+self.VIRTUAL_DEVICE_OFFSET, "name": device.getProductName(), "type": device_type, "type_description": "Ringer Speaker",
                                          "channel_counts": channel_counts, "is_source": device.isSource(), "is_sink": device.isSink(), "is_comms": False, "is_virtual": True}
                                    virtual_ringers.append(d)
                
                except Exception as e:
                    RNS.log(f"An error occurred while mapping available audio devices: {e}", RNS.LOG_ERROR)
                    RNS.trace_exception(e)

            if not found_ringer:
                RNS.log(f"No native ringer output available on device", RNS.LOG_DEBUG)
                for virtual_ringer in virtual_ringers:
                    RNS.log(f"Adding virtual ringer {virtual_ringer}", RNS.LOG_DEBUG)
                    self.available_devices.append(virtual_ringer)

            # TODO: Remove debug
            RNS.log(f"Discovered audio devices:", RNS.LOG_DEBUG)
            for d in self.available_devices:
                RNS.log(f"    {d}", RNS.LOG_DEBUG)

        except Exception as e:
            RNS.log(f"Error while initializing Android audio backend: {e}", RNS.LOG_ERROR)
            RNS.trace_exception(e)
    
    def _shutdown(self): pass

    @property
    def name(self): return self._client_name

    @name.setter
    def name(self, name): self._client_name = name

    @property
    def source_list(self):
        device_list = []
        for d in self.available_devices:
            if d["is_source"]:
                type_description = d["type_description"]; name = d["name"]; did = d["id"]
                device_list.append({"name": f"{type_description} {name}", "id": did})

        return device_list

    def source_info(self, source_id):
        for d in self.available_devices:
            if d["id"] == source_id:
                type_description = d["type_description"]; name = d["name"]; did = d["id"]
                if   2 in d["channel_counts"]: channels = 2
                elif 1 in d["channel_counts"]: channels = 1
                else: raise ValueError(f"Unsupported channel count on source {type_description} {name} ({source_id})")
                return {"latency": 0, "configured_latency": 0, "channels": channels, "name": f"{type_description} {name}", "device.class": "sound", "device.api": "JNI", "device.bus": "unknown"}
    
        return None
        
    @property
    def sink_list(self):
        device_list = []
        for d in self.available_devices:
            if d["is_sink"]:
                type_description = d["type_description"]; name = d["name"]; did = d["id"]
                device_list.append({"name": f"{type_description} {name}", "id": did})

        return device_list

    def sink_info(self, sink_id):
        for d in self.available_devices:
            if d["id"] == sink_id:
                type_description = d["type_description"]; name = d["name"]; did = d["id"]
                if   2 in d["channel_counts"]: channels = 2
                elif 1 in d["channel_counts"]: channels = 1
                else: raise ValueError(f"Unsupported channel count on source {type_description} {name} ({sink_id})")
                return {"latency": 0, "configured_latency": 0, "channels": channels, "name": f"{type_description} {name}", "device.class": "sound", "device.api": "JNI", "device.bus": "unknown"}
    
        return None

    @property
    def server_info(self):
        default_source_id = None
        default_sink_id = None

        for d in self.available_devices:
            if d["type_description"] == self.DEFAULT_SOURCE:
                default_source_id = d["id"]
                break

        if not default_source_id:
            RNS.log(f"Default sink not found, searching for fallback...", RNS.LOG_DEBUG)
            for fallback_source in self.FALLBACK_SOURCES:
                if default_source_id != None: break
                for d in self.available_devices:
                    if d["is_source"] == True and d["type_description"] == fallback_source:
                        RNS.log(f"Found fallback source: {fallback_source}", RNS.LOG_DEBUG)
                        default_source_id = d["id"]
                        break

        for d in self.available_devices:
            if d["type_description"] == self.DEFAULT_SINK:
                default_sink_id = d["id"]
                break

        if not default_sink_id:
            RNS.log(f"Default sink not found, searching for fallback...", RNS.LOG_DEBUG)
            for fallback_sink in self.FALLBACK_SINKS:
                if default_sink_id != None: break
                for d in self.available_devices:
                    if d["is_sink"] == True and d["type_description"] == fallback_sink:
                        RNS.log(f"Found fallback sink: {fallback_sink}", RNS.LOG_DEBUG)
                        default_sink_id = d["id"]
                        break

        if not default_sink_id or not default_source_id: RNS.log(f"Failed to find default devices. Available devices on this system are: {self.available_devices}", RNS.LOG_ERROR)
        if not default_source_id: raise OSError("Could not determine default audio input device, no suitable device available")
        if not default_sink_id: raise OSError("Could not determine default audio output device, no suitable device available")
        info = {"server version": "1.0.0", "server name": "Android Audio", "default sink id": default_sink_id, "default source id": default_source_id}
        return info

_audio = _AndroidAudio()
atexit.register(_audio._shutdown)

def all_speakers(): return [_Speaker(id=s['id']) for s in _audio.sink_list]

def default_speaker():
    name = _audio.server_info["default sink id"]
    return get_speaker(name)

def get_speaker(id, low_latency=False):
    speakers = _audio.sink_list
    return _Speaker(id=_match_soundcard(id, speakers)['id'], low_latency=low_latency)

def all_microphones(include_loopback=False, exclude_monitors=True):
    if not exclude_monitors: include_loopback = not exclude_monitors
    mics = [_Microphone(id=m['id']) for m in _audio.source_list]
    if not include_loopback: return [m for m in mics if m._get_info()['device.class'] != 'monitor']
    else: return mics

def default_microphone():
    name = _audio.server_info['default source id']
    return get_microphone(name, include_loopback=True)

def get_microphone(id, include_loopback=False, exclude_monitors=True):
    if not exclude_monitors: include_loopback = not exclude_monitors
    microphones = _audio.source_list
    return _Microphone(id=_match_soundcard(id, microphones, include_loopback)['id'])

def _match_soundcard(id, soundcards, include_loopback=False):
    soundcards_by_id = {soundcard['id']: soundcard for soundcard in soundcards}
    soundcards_by_name = {soundcard['name']: soundcard for soundcard in soundcards}
    
    if id in soundcards_by_id: return soundcards_by_id[id]

    for name, soundcard in soundcards_by_name.items():
        if id in name: return soundcard
    
    pattern = ".*".join(id)
    for name, soundcard in soundcards_by_name.items():
        if re.match(pattern, name): return soundcard
    raise IndexError(f"no soundcard with id {id}")

def get_name(): return _audio.name

def set_name(name): _audio.name = name


class _SoundCard:
    def __init__(self, *, id, low_latency=False):
        self._id = id
        self._low_latency = low_latency

    @property
    def channels(self): return self._get_info()['channels']

    @property
    def id(self): return self._id

    @property
    def name(self): return self._get_info()['name']

    def _get_info(self): return _audio.source_info(self._id)


class _Speaker(_SoundCard):

    def __repr__(self):
        return '<Speaker {} ({} channels)>'.format(self.name, self.channels)

    def player(self, samplerate, channels=None, blocksize=None, low_latency=None):
        if channels is None: channels = self.channels
        return _Player(self._id, samplerate, channels, blocksize, low_latency)

    def play(self, data, samplerate, channels=None, blocksize=None):
        if channels is None: channels = self.channels
        with _Player(self._id, samplerate, channels, blocksize) as s: s.play(data)

    def _get_info(self): return _audio.sink_info(self._id)


class _Microphone(_SoundCard):

    def __repr__(self):
        if self.isloopback: return '<Loopback {} ({} channels)>'.format(self.name, self.channels)
        else:               return '<Microphone {} ({} channels)>'.format(self.name, self.channels)

    @property
    def isloopback(self):
        return False

    def recorder(self, samplerate, channels=None, blocksize=None):
        if channels is None: channels = self.channels
        return _Recorder(self._id, samplerate, channels, blocksize)

    def record(self, numframes, samplerate, channels=None, blocksize=None):
        if channels is None: channels = self.channels
        with _Recorder(self._id, samplerate, channels, blocksize) as r: return r.record(numframes)


class _Stream:
    TYPE_MAP_FACTOR = numpy.iinfo("int16").max

    def __init__(self, id, samplerate, channels, blocksize=None, name="outputstream", low_latency=None):
        self._id                 = id
        self._samplerate         = samplerate
        self._name               = name
        self._blocksize          = blocksize
        self.channels            = channels
        self.bit_depth           = 16
        self.audio_track         = None
        self.audio_record        = None
        self.audio_mode          = "normal"
        self.enabled_comms       = False
        self.low_latency_allowed = low_latency

        try:
            Context  = autoclass('android.content.Context')
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            
            if activity == None:
                RNS.log(f"Could not obtain application context, instance may be running in a service context.", RNS.LOG_DEBUG)
                android_service = autoclass('org.kivy.android.PythonService').mService
                activity        = android_service.getApplication().getApplicationContext()
                if activity    != None: RNS.log(f"Successfully obtained application context from service", RNS.LOG_DEBUG)

            if activity == None:
                RNS.log(f"Failed to obtain application context for audio stream acquisition", RNS.LOG_ERROR)
                raise ValueError("No application context available for audio stream acquisition")

            self.AudioManager        = activity.getSystemService(autoclass("android.media.AudioManager"))
            self.AudioTrack          = autoclass("android.media.AudioTrack")
            self.AudioFormat         = autoclass("android.media.AudioFormat")
            self.AudioDeviceInfo     = autoclass("android.media.AudioDeviceInfo")

            self.audio_encoding      = self.AudioFormat.ENCODING_PCM_16BIT
            self.audio_track_mode    = self.AudioTrack.MODE_STREAM

            target_device_info = None
            for d in _audio.available_devices:
                if d["id"] == self._id:
                    target_device_info = d
                    break

            if not target_device_info:
                RNS.log(f"Could not acquire target audio device with ID {self._id}, using fallback", RNS.LOG_WARNING)
                self.audio_track_profile = self.AudioManager.STREAM_VOICE_CALL

            else:
                self.audio_track_profile = self.AudioManager.STREAM_VOICE_CALL

                # We can only select by sink for now, as Android insists on auto-
                # selecting matching sources in the setCommunicationDevice API
                if target_device_info["is_sink"]:
                    target_device_id = target_device_info["id"]
                    if target_device_info["is_virtual"]:
                        RNS.log(f"{self} USING VIRTUAL RINGER")
                        target_device_id -= _audio.VIRTUAL_DEVICE_OFFSET

                    if _audio.android_api_version < 31:
                        available_devices = self.AudioManager.getDevices(self.AudioManager.GET_DEVICES_ALL)
                        comms_devices     = []
                    else:
                        available_devices = self.AudioManager.getDevices(self.AudioManager.GET_DEVICES_ALL)
                        comms_devices     = self.AudioManager.getAvailableCommunicationDevices()

                    target_device    = None
                    is_comms_device  = False
                    is_ringer_device = False

                    for device in comms_devices:
                        if target_device_id == device.getId():
                            target_device = device
                            is_comms_device = True
                            break

                    if target_device == None:
                        for device in available_devices:
                            if target_device_id == device.getId():
                                target_device = device
                                is_comms_device = False
                                break

                    device_id   = device.getId()
                    device_type = device.getType()

                    if target_device_info["type_description"] == "Ringer Speaker":
                        self.AudioManager.setMode(self.AudioManager.MODE_NORMAL)
                        self.audio_mode = "ringer"
                        RNS.log("Enabled ringer audio mode", RNS.LOG_DEBUG)

                    else:
                        if _audio.android_api_version >= 34:
                            if device_type in _audio.device_type_descriptions and _audio.device_type_descriptions[device_type] in _audio.COMMUNICATION_MODE_TYPES:
                                self.AudioManager.setMode(self.AudioManager.MODE_IN_COMMUNICATION)
                                self.audio_mode = "communication"
                                self.enabled_comms = True
                                RNS.log("Enabled communications audio mode", RNS.LOG_DEBUG)
                                if is_comms_device:
                                    RNS.log(f"Running on API level {_audio.android_api_version}, setting via setCommunicationDevice", RNS.LOG_DEBUG)
                                    if self.AudioManager.setCommunicationDevice(device):
                                        RNS.log(f"Successfully configured communication device to: {device} / {device.getType()}", RNS.LOG_DEBUG)
                            
                            else:
                                self.AudioManager.setMode(self.AudioManager.MODE_NORMAL)
                                self.audio_mode = "normal"
                                RNS.log("Enabled normal audio mode", RNS.LOG_DEBUG)

                        else:
                            RNS.log(f"Running on API level {_audio.android_api_version}, setting via setSpeakerphoneOn", RNS.LOG_DEBUG)
                            if device_type in _audio.device_type_descriptions and _audio.device_type_descriptions[device_type] in _audio.COMMUNICATION_MODE_TYPES:
                                self.AudioManager.setMode(self.AudioManager.MODE_IN_COMMUNICATION)
                                self.AudioManager.setSpeakerphoneOn(False)
                                RNS.log("Enabled communications audio mode", RNS.LOG_DEBUG)
                            
                            else:
                                # API levels < 34, we'll apparently have to set communications mode
                                # no matter what, since otherwise the microphone will be muted.
                                self.AudioManager.setMode(self.AudioManager.MODE_IN_COMMUNICATION)
                                self.AudioManager.setSpeakerphoneOn(True)
                                RNS.log("Enabled communications audio mode", RNS.LOG_DEBUG)

                    # for device in available_devices:
                    #     device_id = device.getId(); device_type = device.getType()
                    #     if target_device_id == device_id:
                    #         if _audio.android_api_version >= 34:
                    #             RNS.log(f"Running on API level {_audio.android_api_version}, setting via setCommunicationDevice", RNS.LOG_DEBUG)
                    #             if device_type in _audio.device_type_descriptions and _audio.device_type_descriptions[device_type] in _audio.COMMUNICATION_MODE_TYPES:
                    #                 self.AudioManager.setMode(self.AudioManager.MODE_IN_COMMUNICATION)
                    #                 self.audio_mode = "communication"
                    #                 self.enabled_comms = True
                    #                 RNS.log("Enabled communications audio mode", RNS.LOG_DEBUG)
                                
                    #             elif target_device_info["type_description"] == "Ringer Speaker":
                    #                 self.AudioManager.setMode(self.AudioManager.MODE_NORMAL)
                    #                 self.audio_mode = "ringer"
                    #                 RNS.log("Enabled ringer audio mode", RNS.LOG_DEBUG)
                                
                    #             else:
                    #                 self.AudioManager.setMode(self.AudioManager.MODE_NORMAL)
                    #                 self.audio_mode = "normal"
                    #                 RNS.log("Enabled normal audio mode", RNS.LOG_DEBUG)
                                
                    #             if self.AudioManager.setCommunicationDevice(device):
                    #                 RNS.log(f"Successfully configured communication device to: {device} / {device.getType()}", RNS.LOG_DEBUG)
                    #                 break

                    #         else:
                    #             RNS.log(f"Running on API level {_audio.android_api_version}, setting via setSpeakerphoneOn", RNS.LOG_DEBUG)
                    #             if device_type in _audio.device_type_descriptions and _audio.device_type_descriptions[device_type] in _audio.COMMUNICATION_MODE_TYPES:
                    #                 self.AudioManager.setMode(self.AudioManager.MODE_IN_COMMUNICATION)
                    #                 self.AudioManager.setSpeakerphoneOn(False)
                    #                 RNS.log("Enabled communications audio mode", RNS.LOG_DEBUG)
                    #             else:
                    #                 # API levels < 34, we'll apparently have to set communications mode
                    #                 # no matter what, since otherwise the microphone will be muted.
                    #                 self.AudioManager.setMode(self.AudioManager.MODE_IN_COMMUNICATION)
                    #                 self.AudioManager.setSpeakerphoneOn(True)
                    #                 RNS.log("Enabled communications audio mode", RNS.LOG_DEBUG)

            if self.channels == 1:
                self.audio_format_out = self.AudioFormat.CHANNEL_OUT_MONO
                self.audio_format_in  = self.AudioFormat.CHANNEL_IN_MONO
            
            elif self.channels == 2:
                self.audio_format_out = self.AudioFormat.CHANNEL_OUT_STEREO
                self.audio_format_in  = self.AudioFormat.CHANNEL_IN_STEREO

            else: raise ValueError(f"Unsupported channel count {channels} on Android audio backend")

            self.min_buffer_playback  = self.AudioTrack.getMinBufferSize(self._samplerate, self.audio_format_out, self.audio_encoding);
            self.min_buffer_recording = self.AudioTrack.getMinBufferSize(self._samplerate, self.audio_format_in, self.audio_encoding);
            self.bytes_per_sample = (self.bit_depth//8)*self.channels

            self._samplerate = int(self.AudioManager.getProperty(self.AudioManager.PROPERTY_OUTPUT_SAMPLE_RATE))
            self.optimal_frames_per_buffer = int(self.AudioManager.getProperty(self.AudioManager.PROPERTY_OUTPUT_FRAMES_PER_BUFFER))
        
        except Exception as e:
            RNS.log(f"Could not initialize Android audio context for {self}: {e}", RNS.LOG_ERROR)
            RNS.trace_exception(e)

    def __enter__(self):
        if isinstance(self.channels, collections.abc.Iterable): channel_count = len(self.channels)
        elif isinstance(self.channels, int): channel_count = self.channels
        else: raise TypeError('channels must be iterable or integer')
        
        numchannels = self.channels if isinstance(self.channels, int) else len(self.channels)
        self._connect_stream()
        if not self.audio_track and not self.audio_record:
            RNS.log(f"Failed to acquire audio stream for {self}", RNS.LOG_ERROR)
            return None

        self.channels = numchannels
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.audio_track:
            self.audio_track.stop()
            self.audio_track.release()

        if self.audio_record:
            self.audio_record.stop()
            self.audio_record.release()

        if self.enabled_comms:
            RNS.log(f"{self} clearing communication device", RNS.LOG_DEBUG)
            self.AudioManager.clearCommunicationDevice()

    @property
    def latency(self):
        # TODO: Get actual stream latency via JNI here
        return 0.001

class _Player(_Stream):
    def _connect_stream(self):
        try:
            AudioAttributes = autoclass("android.media.AudioAttributes")
            AudioAttributesBuilder = autoclass("android.media.AudioAttributes$Builder")
            AudioFormat = autoclass("android.media.AudioFormat")
            AudioFormatBuilder = autoclass("android.media.AudioFormat$Builder")
            AudioTrack = autoclass("android.media.AudioTrack")
            AudioTrackBuilder = autoclass("android.media.AudioTrack$Builder")

            self._target_buffer_samples = None
            self._play_engaged = False
            self._low_latency = False
            self._low_latency_activated = False
            self._successful_buffer_frames = None
            self._last_underruns = 0
            self._write_mode = AudioTrack.WRITE_BLOCKING
            self._sample_time = 1.0/self._samplerate
            self._target_buffer_ms = 125
            self._overrun_wait = (self._target_buffer_ms*0.1)/1000
            self._overrun_lock = 0

            aa_builder = AudioAttributesBuilder()
            if self.audio_mode == "normal":
                RNS.log(f"Enabling stream properties for normal mode", RNS.LOG_DEBUG)
                aa_builder.setUsage(AudioAttributes.USAGE_MEDIA)
                aa_builder.setContentType(AudioAttributes.CONTENT_TYPE_UNKNOWN)
                self.performance_mode = AudioTrack.PERFORMANCE_MODE_LOW_LATENCY
                if self.low_latency_allowed: self._low_latency = True

            elif self.audio_mode == "communication":
                RNS.log(f"Enabling stream properties for communication mode", RNS.LOG_DEBUG)
                aa_builder.setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                aa_builder.setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                self.performance_mode = AudioTrack.PERFORMANCE_MODE_LOW_LATENCY
                if self.low_latency_allowed: self._low_latency = True

            elif self.audio_mode == "ringer":
                RNS.log(f"Enabling stream properties for ringer mode", RNS.LOG_DEBUG)
                aa_builder.setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                aa_builder.setContentType(AudioAttributes.CONTENT_TYPE_UNKNOWN)
                self.performance_mode = AudioTrack.PERFORMANCE_MODE_NONE

            else:
                RNS.log(f"Enabling stream properties for non-specific mode", RNS.LOG_DEBUG)
                aa_builder.setUsage(AudioAttributes.USAGE_MEDIA)
                aa_builder.setContentType(AudioAttributes.CONTENT_TYPE_UNKNOWN)
                self.performance_mode = AudioTrack.PERFORMANCE_MODE_NONE

            aa_builder.setAllowedCapturePolicy(AudioAttributes.ALLOW_CAPTURE_BY_NONE)
            self.audio_attributes = aa_builder.build()

            af_builder = AudioFormatBuilder()
            af_builder.setSampleRate(int(self._samplerate))
            af_builder.setEncoding(self.audio_encoding)
            af_builder.setChannelMask(self.audio_format_out)
            self.audio_format = af_builder.build()

            at_builder = AudioTrackBuilder()
            at_builder.setAudioAttributes(self.audio_attributes)
            at_builder.setAudioFormat(self.audio_format)
            at_builder.setBufferSizeInBytes(self.min_buffer_playback)
            at_builder.setPerformanceMode(self.performance_mode)
            self.audio_track = at_builder.build()
            
            if self._low_latency: self._low_latency_setup()

        except Exception as e:
            RNS.log(f"Error while connecting output audio stream via JNI: {e}", RNS.LOG_ERROR)
            RNS.trace_exception(e)

    def enable_low_latency(self):
        self.low_latency_allowed = True
        self._low_latency = True
        self._low_latency_setup()
        if self.audio_track and self._play_engaged:
            self.audio_track.setBufferSizeInFrames(self._target_buffer_samples)

    def _low_latency_setup(self):
        AudioTrack = autoclass("android.media.AudioTrack")
        self._write_mode = AudioTrack.WRITE_NON_BLOCKING
        self._target_buffer_samples = int((self._target_buffer_ms/1000.0)/(1.0/self._samplerate))
        self.audio_track.setBufferSizeInFrames(self._target_buffer_samples)
        self._low_latency_activated = True

    def play(self, frame):
        if not self.audio_track: return

        input_samples = frame*self.TYPE_MAP_FACTOR
        data = input_samples.astype(numpy.int16)

        if data.ndim == 1:                            data = data[:, None] # Force 2D array
        if data.ndim != 2:                            raise TypeError(f"data must be 1d or 2d, not {data.ndim}d")
        if data.shape[1] == 1 and self.channels != 1: data = numpy.tile(data, [1, self.channels])
        if data.shape[1] != self.channels:            raise TypeError(f"second dimension of data must be equal to the number of channels, not {data.shape[1]}")
        
        while data.nbytes > 0:
            samples_bytes     = data.ravel().tobytes()
            written_bytes     = self.audio_track.write(samples_bytes, 0, len(samples_bytes), self._write_mode)
            written_samples   = written_bytes//self.bytes_per_sample

            if self._low_latency_activated:
                if written_samples > 0:
                    written_time       = written_samples*self._sample_time
                    min_wait           = written_time*0.25
                    self._overrun_lock = time.time()+(written_time*1.0)
                    time.sleep(min_wait)
                
                if written_bytes == 0:
                    if time.time() > self._overrun_lock:
                        remaining_frame_samples = len(data)
                        written_samples = remaining_frame_samples
                        # TODO: Remove debug
                        # RNS.log(f"Buffer overrun. Target buffer samples {self._target_buffer_samples}. Needed to write {remaining_frame_samples} samples / {len(samples_bytes)} bytes. Discarding {written_samples} input samples.")

            data = data[written_samples:]

            if not self._play_engaged:
                self.audio_track.play()
                self._play_engaged = True
                if self._target_buffer_samples: self.audio_track.setBufferSizeInFrames(self._target_buffer_samples)

            underruns = self.audio_track.getUnderrunCount()
            if underruns > self._last_underruns:
                delta = underruns-self._last_underruns
                self._last_underruns = underruns
                # TODO: Remove debug
                # RNS.log(f"{delta} underruns on {self}")

class _Recorder(_Stream):
    def __init__(self, *args, **kwargs):
        super(_Recorder, self).__init__(*args, **kwargs)
        self.AudioRecord = autoclass("android.media.AudioRecord")
        self._pending_chunk = numpy.zeros((0, ), dtype='float32')

    def _connect_stream(self):
        try:
            AudioSource = autoclass("android.media.MediaRecorder$AudioSource")

            self.audio_record = self.AudioRecord(AudioSource.VOICE_COMMUNICATION, self._samplerate, self.audio_format_in, self.audio_encoding, self.min_buffer_recording)
            self.audio_record.startRecording()

        except Exception as e:
            RNS.log(f"Error while connecting input audio stream via JNI: {e}", RNS.LOG_ERROR)
            RNS.trace_exception(e)

    def _record_chunk(self):
        try:
            audio_data = bytearray(self.min_buffer_recording)
            bytes_read = self.audio_record.read(audio_data, 0, self.min_buffer_recording, self.audio_record.READ_NON_BLOCKING)
            if bytes_read == 0: time.sleep(0.005)

            if   bytes_read == self.audio_record.ERROR_INVALID_OPERATION: RNS.log(f"Invalid operation error from JNI on {self}", RNS.LOG_ERROR)
            elif bytes_read == self.audio_record.ERROR_BAD_VALUE:         RNS.log(f"Bad value error from JNI on {self}", RNS.LOG_ERROR)
            else:
                recorded_samples = numpy.frombuffer(audio_data[:bytes_read], dtype="int16")/self.TYPE_MAP_FACTOR
                return recorded_samples.astype("float32")

        except Exception as e:
            RNS.log(f"Error while reading audio chunk: {e}", RNS.LOG_ERROR)
            RNS.trace_exception(e)
            return None


    def record(self, numframes=None):
        if numframes is None: return numpy.reshape(numpy.concatenate([self.flush().ravel(), self._record_chunk()]), [-1, self.channels])
        else:
            captured_data = [self._pending_chunk]
            captured_frames = self._pending_chunk.shape[0] / self.channels
            if captured_frames >= numframes:
                keep, self._pending_chunk = numpy.split(self._pending_chunk, [int(numframes * self.channels)])
                return numpy.reshape(keep, [-1, self.channels])
            
            else:
                while captured_frames < numframes:
                    chunk = self._record_chunk()
                    captured_data.append(chunk)
                    captured_frames += len(chunk)/self.channels
                
                to_split = int(len(chunk) - (captured_frames - numframes) * self.channels)
                captured_data[-1], self._pending_chunk = numpy.split(captured_data[-1], [to_split])
                return numpy.reshape(numpy.concatenate(captured_data), [-1, self.channels])

    def flush(self):
        last_chunk = numpy.reshape(self._pending_chunk, [-1, self.channels])
        self._pending_chunk = numpy.zeros((0, ), dtype="float32")
        return last_chunk
