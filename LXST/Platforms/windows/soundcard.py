# Adapted from Bastian Bechtold's soundcard library, originally released
# under the BSD 3-Clause License
#
# https://github.com/bastibe/SoundCard
#
# Copyright (c) 2016 Bastian Bechtold
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the
#    distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# Modifications and improvements Copyright 2025 Mark Qvist, and released
# under the same BSD 3-Clause License.

import os
import cffi
import re
import time
import struct
import collections
import platform
import warnings
import threading
import numpy
import RNS

_ffi = cffi.FFI()
_package_dir, _ = os.path.split(__file__)
with open(os.path.join(_package_dir, 'mediafoundation.h'), 'rt') as f: _ffi.cdef(f.read())
try: _ole32 = _ffi.dlopen('ole32')
except OSError:
    try: _ole32 = _ffi.dlopen('ole32.dll')
    except: raise SystemError("LXST Could not load OLE32 DLL for WASAPI integration")

def tid(): return threading.get_native_id()
com_thread_ids = []
class _COMLibrary:
    def __init__(self):
        self._lock = threading.Lock()
        self.init_com()

    def init_com(self):
        with self._lock:
            if tid() in com_thread_ids: return
            else:
                com_thread_ids.append(tid())
                COINIT_MULTITHREADED = 0x0
                RNS.log(f"COM init from thread {tid()}", RNS.LOG_EXTREME)
                if platform.win32_ver()[0] == "8": raise OSError("Unsupported Windows version")
                else: hr = _ole32.CoInitializeEx(_ffi.NULL, COINIT_MULTITHREADED)

                try:
                    self.check_error(hr)
                    self.com_loaded = True
                except RuntimeError as e:
                    # Error 0x80010106 - COM already initialized
                    RPC_E_CHANGED_MODE = 0x80010106
                    if hr + 2 ** 32 == RPC_E_CHANGED_MODE: self.com_loaded = False
                    else: raise e

    def release_com(self):
        with self._lock:
            if tid() in com_thread_ids:
                com_thread_ids.remove(tid())
                RNS.log(f"COM release from thread {tid()}", RNS.LOG_EXTREME)
                if _ole32 != None: _ole32.CoUninitialize()
                else: RNS.log(f"OLE32 instance was None at de-init for thread {tid()}", RNS.LOG_DEBUG)

    def __del__(self): self.release_com()

    @staticmethod
    def check_error(hresult):
        S_OK = 0
        E_NOINTERFACE = 0x80004002
        E_POINTER = 0x80004003
        E_OUTOFMEMORY = 0x8007000e
        E_INVALIDARG = 0x80070057
        CO_E_NOTINITIALIZED = 0x800401f0
        AUDCLNT_E_UNSUPPORTED_FORMAT = 0x88890008
        if hresult == S_OK: return
        elif hresult+2**32 == E_NOINTERFACE: raise RuntimeError("The specified class does not implement the requested interface, or the controlling IUnknown does not expose the requested interface.")
        elif hresult+2**32 == E_POINTER:     raise RuntimeError("An argument is NULL")
        elif hresult+2**32 == E_INVALIDARG:  raise RuntimeError("Invalid argument")
        elif hresult+2**32 == E_OUTOFMEMORY: raise RuntimeError("Out of memory")
        elif hresult+2**32 == AUDCLNT_E_UNSUPPORTED_FORMAT: raise RuntimeError("Unsupported format")
        elif hresult+2**32 == CO_E_NOTINITIALIZED:          raise RuntimeError(f"Windows COM context not initialized in {tid()}")
        else:                                               raise RuntimeError("Error {}".format(hex(hresult+2**32)))

    @staticmethod
    def release(ppObject):
        if ppObject[0] != _ffi.NULL:
            ppObject[0][0].lpVtbl.Release(ppObject[0])
            ppObject[0] = _ffi.NULL

_com = _COMLibrary()

def all_speakers():
    with _DeviceEnumerator() as enum:
        return [_Speaker(dev) for dev in enum.all_devices('speaker')]

def default_speaker():
    with _DeviceEnumerator() as enum:
        return _Speaker(enum.default_device('speaker'))

def get_speaker(id):
    return _match_device(id, all_speakers())

def all_microphones(include_loopback=False):
    with _DeviceEnumerator() as enum:
        if include_loopback:
            return [_Microphone(dev, isloopback=True) for dev in enum.all_devices('speaker')] + [_Microphone(dev) for dev in enum.all_devices('microphone')]
        else:
            return [_Microphone(dev) for dev in enum.all_devices('microphone')]

def default_microphone():
    with _DeviceEnumerator() as enum:
        return _Microphone(enum.default_device('microphone'))

def get_microphone(id, include_loopback=False):
    return _match_device(id, all_microphones(include_loopback))

def _match_device(id, devices):
    devices_by_id = {device.id: device for device in devices}
    devices_by_name = {device.name: device for device in devices}
    if id in devices_by_id: return devices_by_id[id]
    
    # Try substring match:
    for name, device in devices_by_name.items():
        if id in name: return device
    
    # Try fuzzy match:
    pattern = '.*'.join(id)
    for name, device in devices_by_name.items():
        if re.match(pattern, name): return device
    
    raise IndexError('No device with id {}'.format(id))

def _str2wstr(string):
    return _ffi.new('int16_t[]', [ord(s) for s in string]+[0])

def _guidof(uuid_str):
    IID = _ffi.new('LPIID')
    uuid = _str2wstr(uuid_str)
    hr = _ole32.IIDFromString(_ffi.cast("char*", uuid), IID)
    _com.check_error(hr)
    return IID

def get_name(): raise NotImplementedError()
def set_name(name): raise NotImplementedError()

class _DeviceEnumerator:
    # See shared/WTypesbase.h and um/combaseapi.h:
    def __init__(self):
        _com.init_com()
        self._ptr = _ffi.new('IMMDeviceEnumerator **')
        IID_MMDeviceEnumerator = _guidof("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
        IID_IMMDeviceEnumerator = _guidof("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        CLSCTX_ALL = 23
        hr = _ole32.CoCreateInstance(IID_MMDeviceEnumerator, _ffi.NULL, CLSCTX_ALL, IID_IMMDeviceEnumerator, _ffi.cast("void **", self._ptr))
        _com.check_error(hr)

    def __enter__(self):
        _com.init_com()
        return self

    def __exit__(self, exc_type, exc_value, traceback): _com.release(self._ptr)
    def __del__(self): _com.release(self._ptr)

    def _device_id(self, device_ptr):
        ppId = _ffi.new('LPWSTR *')
        hr = device_ptr[0][0].lpVtbl.GetId(device_ptr[0], ppId)
        _com.check_error(hr)
        return _ffi.string(ppId[0])

    def all_devices(self, kind):
        if kind == 'speaker': data_flow = 0 # render
        elif kind == 'microphone': data_flow = 1 # capture
        else: raise TypeError('Invalid kind: {}'.format(kind))

        DEVICE_STATE_ACTIVE = 0x1
        ppDevices = _ffi.new('IMMDeviceCollection **')
        hr = self._ptr[0][0].lpVtbl.EnumAudioEndpoints(self._ptr[0], data_flow, DEVICE_STATE_ACTIVE, ppDevices);
        _com.check_error(hr)

        for ppDevice in _DeviceCollection(ppDevices):
            device = _Device(self._device_id(ppDevice))
            _com.release(ppDevice)
            yield device

    def default_device(self, kind):
        if kind == 'speaker': data_flow = 0 # render
        elif kind == 'microphone': data_flow = 1 # capture
        else: raise TypeError('Invalid kind: {}'.format(kind))

        ppDevice = _ffi.new('IMMDevice **')
        eConsole = 0
        hr = self._ptr[0][0].lpVtbl.GetDefaultAudioEndpoint(self._ptr[0], data_flow, eConsole, ppDevice);
        _com.check_error(hr)
        device = _Device(self._device_id(ppDevice))
        _com.release(ppDevice)
        return device

    def device_ptr(self, devid):
        ppDevice = _ffi.new('IMMDevice **')
        devid = _str2wstr(devid)
        hr = self._ptr[0][0].lpVtbl.GetDevice(self._ptr[0], _ffi.cast('wchar_t *', devid), ppDevice);
        _com.check_error(hr)
        return ppDevice

class _DeviceCollection:
    def __init__(self, ptr):
        _com.init_com()
        self._ptr = ptr

    def __del__(self): _com.release(self._ptr)

    def __len__(self):
        pCount = _ffi.new('UINT *')
        hr = self._ptr[0][0].lpVtbl.GetCount(self._ptr[0], pCount)
        _com.check_error(hr)
        return pCount[0]

    def __getitem__(self, idx):
        if idx >= len(self):
            raise StopIteration()
        ppDevice = _ffi.new('IMMDevice **')
        hr = self._ptr[0][0].lpVtbl.Item(self._ptr[0], idx, ppDevice)
        _com.check_error(hr)
        return ppDevice

class _PropVariant:
    def __init__(self):
        _com.init_com()
        self.ptr = _ole32.CoTaskMemAlloc(_ffi.sizeof('PROPVARIANT'))
        self.ptr = _ffi.cast("PROPVARIANT *", self.ptr)

    def __del__(self):
        hr = _ole32.PropVariantClear(self.ptr)
        _com.check_error(hr)

class _Device:
    def __init__(self, id):
        _com.init_com()
        self._id = id

    def _device_ptr(self):
        with _DeviceEnumerator() as enum:
            return enum.device_ptr(self._id)

    @property
    def id(self): return self._id

    @property
    def name(self):
        # um/coml2api.h:
        ppPropertyStore = _ffi.new('IPropertyStore **')
        ptr = self._device_ptr()
        hr = ptr[0][0].lpVtbl.OpenPropertyStore(ptr[0], 0, ppPropertyStore)
        _com.release(ptr)
        _com.check_error(hr)
        propvariant = _PropVariant()
        # um/functiondiscoverykeys_devpkey.h and https://msdn.microsoft.com/en-us/library/windows/desktop/dd370812(v=vs.85).aspx
        PKEY_Device_FriendlyName = _ffi.new("PROPERTYKEY *",
                                            [[0xa45c254e, 0xdf1c, 0x4efd, [0x80, 0x20, 0x67, 0xd1, 0x46, 0xa8, 0x50, 0xe0]],
                                            14])
        hr = ppPropertyStore[0][0].lpVtbl.GetValue(ppPropertyStore[0], PKEY_Device_FriendlyName, propvariant.ptr)
        _com.check_error(hr)
        if propvariant.ptr[0].vt != 31:
            raise RuntimeError('Property was expected to be a string, but is not a string')
        data = _ffi.cast("short*", propvariant.ptr[0].data)
        for idx in range(256):
            if data[idx] == 0: break
        devicename = struct.pack('h' * idx, *data[0:idx]).decode('utf-16')
        _com.release(ppPropertyStore)
        return devicename

    @property
    def channels(self):
        # um/coml2api.h:
        ppPropertyStore = _ffi.new('IPropertyStore **')
        ptr = self._device_ptr()
        hr = ptr[0][0].lpVtbl.OpenPropertyStore(ptr[0], 0, ppPropertyStore)
        _com.release(ptr)
        _com.check_error(hr)
        propvariant = _PropVariant()
        # um/functiondiscoverykeys_devpkey.h and https://msdn.microsoft.com/en-us/library/windows/desktop/dd370812(v=vs.85).aspx
        PKEY_AudioEngine_DeviceFormat = _ffi.new("PROPERTYKEY *",
                                                 [[0xf19f064d, 0x82c, 0x4e27, [0xbc, 0x73, 0x68, 0x82, 0xa1, 0xbb, 0x8e, 0x4c]],
                                                  0])
        hr = ppPropertyStore[0][0].lpVtbl.GetValue(ppPropertyStore[0], PKEY_AudioEngine_DeviceFormat, propvariant.ptr)
        _com.release(ppPropertyStore)
        _com.check_error(hr)
        if propvariant.ptr[0].vt != 65:
            raise RuntimeError('Property was expected to be a blob, but is not a blob')
        pPropVariantBlob = _ffi.cast("BLOB_PROPVARIANT *", propvariant.ptr)
        assert pPropVariantBlob[0].blob.cbSize == 40
        waveformat = _ffi.cast("WAVEFORMATEX *", pPropVariantBlob[0].blob.pBlobData)
        channels = waveformat[0].nChannels
        return channels

    def _audio_client(self):
        CLSCTX_ALL = 23
        ppAudioClient = _ffi.new("IAudioClient **")
        IID_IAudioClient = _guidof("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
        ptr = self._device_ptr()
        hr = ptr[0][0].lpVtbl.Activate(ptr[0], IID_IAudioClient, CLSCTX_ALL, _ffi.NULL, _ffi.cast("void**", ppAudioClient))
        _com.release(ptr)
        _com.check_error(hr)
        return ppAudioClient

class _Speaker(_Device):
    def __init__(self, device): self._id = device._id

    def __repr__(self): return '<Speaker {} ({} channels)>'.format(self.name,self.channels)

    def player(self, samplerate, channels=None, blocksize=None, exclusive_mode=False):
        if channels is None: channels = self.channels
        return _Player(self._audio_client(), samplerate, channels, blocksize, False, exclusive_mode)

    def play(self, data, samplerate, channels=None, blocksize=None):
        with self.player(samplerate, channels, blocksize) as p: p.play(data)


class _Microphone(_Device):
    def __init__(self, device, isloopback=False):
        self._id = device._id
        self.isloopback = isloopback

    def __repr__(self):
        if self.isloopback: return '<Loopback {} ({} channels)>'.format(self.name,self.channels)
        else: return '<Microphone {} ({} channels)>'.format(self.name,self.channels)

    def recorder(self, samplerate, channels=None, blocksize=None, exclusive_mode=False):
        if channels is None: channels = self.channels
        return _Recorder(self._audio_client(), samplerate, channels, blocksize, self.isloopback, exclusive_mode)

    def record(self, numframes, samplerate, channels=None, blocksize=None):
        with self.recorder(samplerate, channels, blocksize) as r: return r.record(numframes)

class _AudioClient:
    def __init__(self, ptr, samplerate, channels, blocksize, isloopback, exclusive_mode=False):
        self._ptr = ptr

        if isinstance(channels, int): self.channelmap = list(range(channels))
        elif isinstance(channels, collections.abc.Iterable): self.channelmap = channels
        else: raise TypeError('Channels must be iterable or integer')

        if list(range(len(set(self.channelmap)))) != sorted(list(set(self.channelmap))):
            raise TypeError('Due to limitations of WASAPI, channel maps on Windows must be a combination of `range(0, x)`.')

        if blocksize is None: blocksize = self.deviceperiod[0]*samplerate

        ppMixFormat = _ffi.new('WAVEFORMATEXTENSIBLE**') # See: https://docs.microsoft.com/en-us/windows/win32/api/mmreg/ns-mmreg-waveformatextensible
        hr = self._ptr[0][0].lpVtbl.GetMixFormat(self._ptr[0], ppMixFormat)
        _com.check_error(hr)

        # It's a WAVEFORMATEXTENSIBLE with room for KSDATAFORMAT_SUBTYPE_IEEE_FLOAT:
        # Note: Some devices may not return 0xFFFE format, but WASAPI should handle conversion
        if ppMixFormat[0][0].Format.wFormatTag == 0xFFFE:
            assert ppMixFormat[0][0].Format.cbSize == 22

            # The data format is float32:
            # These values were found empirically, and I don't know why they work.
            # The program crashes if these values are different
            assert ppMixFormat[0][0].SubFormat.Data1 == 0x100000
            assert ppMixFormat[0][0].SubFormat.Data2 == 0x0080
            assert ppMixFormat[0][0].SubFormat.Data3 == 0xaa00
            assert [int(x) for x in ppMixFormat[0][0].SubFormat.Data4[0:4]] == [0, 56, 155, 113]
            # the last four bytes seem to vary randomly
        else:
            # Device doesn't return WAVEFORMATEXTENSIBLE, but WASAPI will handle conversion
            # Just skip the assertions and let WASAPI convert
            pass

        channels = len(set(self.channelmap))
        channelmask = 0
        for ch in self.channelmap: channelmask |= 1<<ch
        ppMixFormat[0][0].Format.nChannels=channels
        ppMixFormat[0][0].Format.nSamplesPerSec=int(samplerate)
        ppMixFormat[0][0].Format.nAvgBytesPerSec=int(samplerate) * channels * 4
        ppMixFormat[0][0].Format.nBlockAlign=channels * 4
        ppMixFormat[0][0].Format.wBitsPerSample=32
        ppMixFormat[0][0].Samples=dict(wValidBitsPerSample=32)
        # does not work:
        # ppMixFormat[0][0].dwChannelMask=channelmask

        # See: https://docs.microsoft.com/en-us/windows/win32/coreaudio/exclusive-mode-streams
        # nopersist, see: https://docs.microsoft.com/en-us/windows/win32/coreaudio/audclnt-streamflags-xxx-constants
        streamflags =  0x00080000
        if exclusive_mode:
            sharemode = _ole32.AUDCLNT_SHAREMODE_EXCLUSIVE
            periodicity = 0 # 0 uses default, must set value if using AUDCLNT_STREAMFLAGS_EVENTCALLBACK (0x00040000)
            if isloopback: raise RuntimeError("Loopback mode and exclusive mode are incompatible.")
        else:
            sharemode = _ole32.AUDCLNT_SHAREMODE_SHARED
            #               resample   | remix       | better-SRC
            #               rateadjust | autoconvPCM | SRC default quality
            streamflags  |= 0x00100000 | 0x80000000  | 0x08000000 # These flags are only relevant/permitted for shared mode
            periodicity   = 0                                     # Always 0 for shared mode
            if isloopback: streamflags |= 0x00020000              # Loopback only allowed for shared mode

        bufferduration = int(blocksize/samplerate * 10000000) # in hecto-nanoseconds (1000_000_0)
        hr = self._ptr[0][0].lpVtbl.Initialize(self._ptr[0], sharemode, streamflags, bufferduration, periodicity, ppMixFormat[0], _ffi.NULL)
        _com.check_error(hr)
        _ole32.CoTaskMemFree(ppMixFormat[0])

        # save samplerate for later
        self.samplerate = samplerate
        # placeholder for the last time we had audio input available
        self._idle_start_time = None


    @property
    def buffersize(self):
        pBufferSize = _ffi.new("UINT32*")
        hr = self._ptr[0][0].lpVtbl.GetBufferSize(self._ptr[0], pBufferSize)
        _com.check_error(hr)
        return pBufferSize[0]

    @property
    def deviceperiod(self):
        pDefaultPeriod = _ffi.new("REFERENCE_TIME*")
        pMinimumPeriod = _ffi.new("REFERENCE_TIME*")
        hr = self._ptr[0][0].lpVtbl.GetDevicePeriod(self._ptr[0], pDefaultPeriod, pMinimumPeriod)
        _com.check_error(hr)
        return pDefaultPeriod[0]/10_000_000, pMinimumPeriod[0]/10_000_000

    @property
    def currentpadding(self):
        pPadding = _ffi.new("UINT32*")
        hr = self._ptr[0][0].lpVtbl.GetCurrentPadding(self._ptr[0], pPadding)
        _com.check_error(hr)
        return pPadding[0]

class _Player(_AudioClient):
    # https://msdn.microsoft.com/en-us/library/windows/desktop/dd316756(v=vs.85).aspx
    def _render_client(self):
        iid = _guidof("{F294ACFC-3146-4483-A7BF-ADDCA7C260E2}")
        ppRenderClient = _ffi.new("IAudioRenderClient**")
        hr = self._ptr[0][0].lpVtbl.GetService(self._ptr[0], iid, _ffi.cast("void**", ppRenderClient))
        _com.check_error(hr)
        return ppRenderClient

    def _render_buffer(self, numframes):
        data = _ffi.new("BYTE**")
        hr = self._ppRenderClient[0][0].lpVtbl.GetBuffer(self._ppRenderClient[0], numframes, data)
        _com.check_error(hr)
        return data

    def _render_release(self, numframes):
        hr = self._ppRenderClient[0][0].lpVtbl.ReleaseBuffer(self._ppRenderClient[0], numframes, 0)
        _com.check_error(hr)

    def _render_available_frames(self):
        return self.buffersize-self.currentpadding

    def __enter__(self):
        _com.init_com()
        self._ppRenderClient = self._render_client()
        hr = self._ptr[0][0].lpVtbl.Start(self._ptr[0])
        _com.check_error(hr)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        hr = self._ptr[0][0].lpVtbl.Stop(self._ptr[0])
        _com.check_error(hr)
        _com.release(self._ppRenderClient)
        _com.release(self._ptr)
        _com.release_com()

    def play(self, data):
        data = numpy.array(data, dtype='float32', order='C')
        if data.ndim == 1: data = data[:, None] # force 2d
        if data.ndim != 2: raise TypeError('Data must be 1d or 2d, not {}d'.format(data.ndim))
        if data.shape[1] == 1 and len(set(self.channelmap)) != 1: data = numpy.tile(data, [1, len(set(self.channelmap))])

        # Internally, channel numbers are always ascending:
        sortidx = sorted(range(len(self.channelmap)), key=lambda k: self.channelmap[k])
        data = data[:, sortidx]

        if data.shape[1] != len(set(self.channelmap)):
            raise TypeError('second dimension of data must be equal to the number of channels, not {}'.format(data.shape[1]))

        while data.nbytes > 0:
            towrite = self._render_available_frames()
            if towrite == 0:
                time.sleep(0.001)
                continue
            
            bytes = data[:towrite].ravel().tobytes()
            buffer = self._render_buffer(towrite)
            _ffi.memmove(buffer[0], bytes, len(bytes))
            self._render_release(towrite)
            data = data[towrite:]

class _Recorder(_AudioClient):
    # https://msdn.microsoft.com/en-us/library/windows/desktop/dd370800(v=vs.85).aspx
    def _capture_client(self):
        iid = _guidof("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
        ppCaptureClient = _ffi.new("IAudioCaptureClient**")
        hr = self._ptr[0][0].lpVtbl.GetService(self._ptr[0], iid, _ffi.cast("void**", ppCaptureClient))
        _com.check_error(hr)
        return ppCaptureClient

    def _capture_buffer(self):
        data = _ffi.new("BYTE**")
        toread = _ffi.new('UINT32*')
        flags = _ffi.new('DWORD*')
        hr = self._ppCaptureClient[0][0].lpVtbl.GetBuffer(self._ppCaptureClient[0], data, toread, flags, _ffi.NULL, _ffi.NULL)
        _com.check_error(hr)
        return data[0], toread[0], flags[0]

    def _capture_release(self, numframes):
        hr = self._ppCaptureClient[0][0].lpVtbl.ReleaseBuffer(self._ppCaptureClient[0], numframes)
        _com.check_error(hr)

    def _capture_available_frames(self):
        pSize = _ffi.new("UINT32*")
        hr = self._ppCaptureClient[0][0].lpVtbl.GetNextPacketSize(self._ppCaptureClient[0], pSize)
        _com.check_error(hr)
        return pSize[0]

    def __enter__(self):
        _com.init_com()
        self._ppCaptureClient = self._capture_client()
        hr = self._ptr[0][0].lpVtbl.Start(self._ptr[0])
        _com.check_error(hr)
        self._pending_chunk = numpy.zeros([0], dtype='float32')
        self._is_first_frame = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        hr = self._ptr[0][0].lpVtbl.Stop(self._ptr[0])
        _com.check_error(hr)
        _com.release(self._ppCaptureClient)
        _com.release(self._ptr)
        _com.release_com()

    def _record_chunk(self):
        while self._capture_available_frames() == 0:
            # Some sound cards indicate silence by not making any
            # frames available. If that is the case, we need to
            # estimate the number of zeros to return, by measuring the
            # silent time:
            if self._idle_start_time is None: self._idle_start_time = time.perf_counter_ns()

            default_block_length, minimum_block_length = self.deviceperiod
            time.sleep(minimum_block_length/4)
            elapsed_time_ns = time.perf_counter_ns() - self._idle_start_time
            
            # Waiting times shorter than a block length or so are
            # normal, and not indicative of a silent sound card. If
            # the waiting times get longer however, we must assume
            # that there is no audio data forthcoming, and return
            # zeros instead:
            if elapsed_time_ns / 1_000_000_000 > default_block_length * 4:
                num_frames = int(self.samplerate * elapsed_time_ns / 1_000_000_000)
                num_channels = len(set(self.channelmap))
                self._idle_start_time += elapsed_time_ns
                return numpy.zeros([num_frames * num_channels], dtype='float32')

        self._idle_start_time = None
        data_ptr, nframes, flags = self._capture_buffer()
        if data_ptr != _ffi.NULL:
            # Convert the raw CFFI buffer into a standard bytes object to ensure compatibility
            # with modern NumPy versions (fromstring binary mode was removed). Using frombuffer
            # on bytes plus .copy() guarantees a writable float32 array for downstream processing.
            buf = bytes(_ffi.buffer(data_ptr, nframes * 4 * len(set(self.channelmap))))
            chunk = numpy.frombuffer(buf, dtype=numpy.float32).copy()
        else: raise RuntimeError('Could not create capture buffer')

        # See https://learn.microsoft.com/en-us/windows/win32/api/audioclient/ne-audioclient-_audclnt_bufferflags
        if flags & _ole32.AUDCLNT_BUFFERFLAGS_SILENT: chunk[:] = 0
        if self._is_first_frame:
            # On first run, clear data discontinuity error, as it will always be set:
            flags &= ~_ole32.AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY
            self._is_first_frame = False
        if flags & _ole32.AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY: pass

        # Ignore _ole32.AUDCLNT_BUFFERFLAGS_TIMESTAMP_ERROR, since we don't use time stamps.
        if nframes > 0:
            self._capture_release(nframes)
            return chunk
        else:
            return numpy.zeros([0], dtype='float32')

    def record(self, numframes=None):
        if numframes is None:
            recorded_data = [self._pending_chunk, self._record_chunk()]
            self._pending_chunk = numpy.zeros([0], dtype='float32')
        
        else:
            recorded_frames = len(self._pending_chunk)
            recorded_data = [self._pending_chunk]
            self._pending_chunk = numpy.zeros([0], dtype='float32')
            required_frames = numframes*len(set(self.channelmap))

            while recorded_frames < required_frames:
                chunk = self._record_chunk()
                if len(chunk) == 0:
                    # No data forthcoming: return zeros
                    chunk = numpy.zeros(required_frames-recorded_frames, dtype='float32')
                recorded_data.append(chunk)
                recorded_frames += len(chunk)

            if recorded_frames > required_frames:
                to_split = -int(recorded_frames-required_frames)
                recorded_data[-1], self._pending_chunk = numpy.split(recorded_data[-1], [to_split])

        data = numpy.reshape(numpy.concatenate(recorded_data), [-1, len(set(self.channelmap))])
        return data[:, self.channelmap]

    def flush(self):
        last_chunk = numpy.reshape(self._pending_chunk, [-1, len(set(self.channelmap))])
        self._pending_chunk = numpy.zeros([0], dtype='float32')
        return last_chunk
