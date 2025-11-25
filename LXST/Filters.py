from importlib.util import find_spec
import numpy as np
import time
import RNS
import os

USE_NATIVE_FILTERS = False
if not find_spec("cffi"):
    RNS.log(f"Could not load CFFI module for filter acceleration, falling back to Python filters. This will be slow.", RNS.LOG_WARNING)
    RNS.log(f"Make sure that the CFFI module is installed and available.", RNS.LOG_WARNING)
else:
    try:
        from cffi import FFI
        import pathlib
        c_src_path = pathlib.Path(__file__).parent.resolve()
        ffi = FFI()

        try:
            if not RNS.vendor.platformutils.is_windows():
                filterlib_spec = find_spec("LXST.filterlib")
                if not filterlib_spec or filterlib_spec.origin == None: raise ImportError("Could not locate pre-compiled LXST.filterlib module")
                with open(os.path.join(c_src_path, "Filters.h"), "r") as f: ffi.cdef(f.read())
                native_functions = ffi.dlopen(filterlib_spec.origin)
                USE_NATIVE_FILTERS = True
            else:
                with open(os.path.join(c_src_path, "Filters.h"), "r") as f: ffi.cdef(f.read())
                native_functions = ffi.dlopen(os.path.join(c_src_path, "filterlib.dll"))
                USE_NATIVE_FILTERS = True
        
        except Exception as e:
            RNS.log(f"Could not load pre-compiled LXST filters library. The contained exception was: {e}", RNS.LOG_WARNING)
            RNS.log(f"Attempting to compile library from source...", RNS.LOG_WARNING)

        if USE_NATIVE_FILTERS == False:
            with open(os.path.join(c_src_path, "Filters.h"), "r") as f: ffi.cdef(f.read())
            with open(os.path.join(c_src_path, "Filters.c"), "r") as f: c_src = f.read()
            native_functions = ffi.verify(c_src)
            USE_NATIVE_FILTERS = True
            RNS.log(f"Successfully compiled and loaded filters library", RNS.LOG_WARNING)

    except Exception as e:
        RNS.log(f"Could not compile modules for filter acceleration, falling back to Python filters. This will be slow.", RNS.LOG_WARNING)
        RNS.log(f"The contained exception was: {e}", RNS.LOG_WARNING)
        USE_NATIVE_FILTERS = False

class Filter():
    def handle_frame(self, frame):
        raise NotImplementedError(f"The handle_frame method was not implemented on {self}")

class HighPass(Filter):
    def __init__(self, cut):
        super().__init__()
        self.cut            = cut
        self._samplerate    = None
        self._channels      = None
        self._filter_states = None
        self._last_inputs   = None
        self._alpha         = None
    
    def handle_frame(self, frame, samplerate):
        if len(frame) == 0: return frame
        if samplerate != self._samplerate:
            self._samplerate = samplerate
            dt = 1.0 / self._samplerate
            rc = 1.0 / (2 * np.pi * self.cut)
            self._alpha = rc / (rc + dt)
        
        if len(frame.shape) == 1: frame_2d = frame.reshape(-1, 1)
        else: frame_2d = frame
        
        samples, channels = frame_2d.shape
        if self._filter_states is None or self._channels != channels:
            self._channels = channels
            self._filter_states = np.zeros(self._channels, dtype=np.float32)
            self._last_inputs = np.zeros(self._channels, dtype=np.float32)
        
        if USE_NATIVE_FILTERS:
            frame_2d = np.ascontiguousarray(frame_2d, dtype=np.float32)
            output = np.empty_like(frame_2d, dtype=np.float32)
            input_ptr = ffi.cast("float *", frame_2d.ctypes.data)
            output_ptr = ffi.cast("float *", output.ctypes.data)
            states_ptr = ffi.cast("float *", self._filter_states.ctypes.data)
            last_inputs_ptr = ffi.cast("float *", self._last_inputs.ctypes.data)
            
            native_functions.highpass_filter(input_ptr, output_ptr, samples, channels, float(self._alpha), states_ptr, last_inputs_ptr)
            
            result = output.reshape(frame.shape)
            return result

        else:
            output = np.empty_like(frame_2d)
            input_diff_first = frame_2d[0] - self._last_inputs
            output[0] = self._alpha * (self._filter_states + input_diff_first)
            
            input_diff = np.empty_like(frame_2d)
            input_diff[0] = input_diff_first
            input_diff[1:] = frame_2d[1:] - frame_2d[:-1]

            for i in range(1, samples):
                output[i] = self._alpha * (output[i-1] + input_diff[i])

            output = self._alpha * (output + input_diff)
            
            self._filter_states = output[-1].copy()
            self._last_inputs = frame_2d[-1].copy()
            
            nframe = output.reshape(frame.shape)
            return nframe

class LowPass(Filter):
    def __init__(self, cut):
        super().__init__()
        self.cut = cut
        self._samplerate = None
        self._channels = None
        self._filter_states = None
        self._alpha = None
    
    def handle_frame(self, frame, samplerate):
        if len(frame) == 0:  return frame
        if samplerate != self._samplerate:
            self._samplerate = samplerate
            dt = 1.0 / self._samplerate
            rc = 1.0 / (2 * np.pi * self.cut)
            self._alpha = dt / (rc + dt)
        
        if len(frame.shape) == 1: frame_2d = frame.reshape(-1, 1)
        else: frame_2d = frame
        
        samples, channels = frame_2d.shape
        
        if self._filter_states is None or self._channels != channels:
            self._channels = channels
            self._filter_states = np.zeros(self._channels, dtype=np.float32)

        if USE_NATIVE_FILTERS:
            frame_2d = np.ascontiguousarray(frame_2d, dtype=np.float32)
            output = np.empty_like(frame_2d, dtype=np.float32)
            input_ptr = ffi.cast("float *", frame_2d.ctypes.data)
            output_ptr = ffi.cast("float *", output.ctypes.data)
            states_ptr = ffi.cast("float *", self._filter_states.ctypes.data)
            
            native_functions.lowpass_filter(input_ptr, output_ptr, samples, channels, float(self._alpha), states_ptr)
            
            return output.reshape(frame.shape)

        else:
            output = np.empty_like(frame_2d)        
            output[0] = self._alpha * frame_2d[0] + (1.0 - self._alpha) * self._filter_states
            for i in range(1, samples):
                output[i] = self._alpha * frame_2d[i] + (1.0 - self._alpha) * output[i-1]
            
            self._filter_states = output[-1].copy()
            
            return output.reshape(frame.shape)

class BandPass(Filter):
    def __init__(self, low_cut, high_cut):
        super().__init__()
        if low_cut >= high_cut: raise ValueError("Low-cut frequency must be less than high-cut frequency")
        self.low_cut    = low_cut
        self.high_cut   = high_cut
        self._high_pass = HighPass(self.low_cut)
        self._low_pass  = LowPass(self.high_cut)
    
    def handle_frame(self, frame, samplerate):
        # TODO: Remove debug
        st = time.time()
        if len(frame) == 0: return frame        
        high_passed    = self._high_pass.handle_frame(frame, samplerate)        
        band_passed    = self._low_pass.handle_frame(high_passed, samplerate)
        dt = time.time()-st
        if dt > 0.010: RNS.log(f"Slow filter processing detected: Filter ran in {RNS.prettyshorttime(time.time()-st)}", RNS.LOG_DEBUG)
        return band_passed

class AGC(Filter):
    def __init__(self, target_level=-12.0, max_gain=12.0, attack_time=0.0001, release_time=0.002, hold_time=0.001):
        super().__init__()
        self.trigger_level     = 0.003
        self.target_level      = target_level # In dBFS
        self.max_gain_db       = max_gain
        self.attack_time       = attack_time
        self.release_time      = release_time
        self.hold_time         = hold_time
        self.target_linear     = 10 ** (target_level / 10)
        self.max_gain_linear   = 10 ** (max_gain / 10)
        self._samplerate       = None
        self._channels         = None
        self._current_gain_lin = 1.0
        self._hold_counter     = 0
        self._block_target_s   = 0.01
        self._attack_coeff     = None
        self._release_coeff    = None
        self._hold_samples     = None
        
    def handle_frame(self, frame, samplerate):
        # TODO: Remove debug
        # st = time.time()
        if len(frame) == 0: return frame
        if len(frame.shape) == 1: frame_2d = frame.reshape(-1, 1)
        else:                     frame_2d = frame
        
        samples, channels = frame_2d.shape
        if samplerate != self._samplerate:
            self._samplerate = samplerate
            self._block_target = int((samples/self._samplerate)/self._block_target_s)
            self._calculate_coefficients()

        if self._channels is None or self._channels != channels:
            self._channels = channels
            self._current_gain_lin = np.ones(channels, dtype=np.float32)
            self._hold_counter = 0

        if USE_NATIVE_FILTERS:
            frame_2d = np.ascontiguousarray(frame_2d, dtype=np.float32)
            output = np.empty_like(frame_2d, dtype=np.float32)            
            input_ptr = ffi.cast("float *", frame_2d.ctypes.data)
            output_ptr = ffi.cast("float *", output.ctypes.data)
            gain_ptr = ffi.cast("float *", self._current_gain_lin.ctypes.data)
            hold_ptr = ffi.new("int *", self._hold_counter)
            
            native_functions.agc_process(
                input_ptr, output_ptr, samples, channels,
                float(self.target_linear), float(self.max_gain_linear), 
                float(self.trigger_level),
                float(self._attack_coeff), float(self._release_coeff), 
                float(self._hold_samples),
                gain_ptr, hold_ptr, int(self._block_target)
            )
            
            self._hold_counter = hold_ptr[0]
            
            result = output.reshape(frame.shape)
            # TODO: Remove debug
            # RNS.log(f"AGC ran in {RNS.prettyshorttime(time.time()-st)}", RNS.LOG_DEBUG)
            return result

        else:
            output = np.empty_like(frame_2d)
            block_size = max(1, samples // self._block_target)
            for i in range(0, samples, block_size):
                block_end = min(i + block_size, samples)
                block = frame_2d[i:block_end]
                block_samples = block_end - i
                
                rms = np.sqrt(np.mean(block ** 2, axis=0))
                target_gain = np.where(rms > 1e-9, self.target_linear / np.maximum(rms, 1e-9), self.max_gain_linear)
                target_gain = np.minimum(target_gain, self.max_gain_linear)
                smoothed_gain = np.empty_like(target_gain)
                
                for ch in range(channels):
                    if (rms[0] < self.trigger_level): target_gain = self._current_gain_lin
                    if target_gain[ch] < self._current_gain_lin[ch]:
                        self._current_gain_lin[ch] = self._attack_coeff * target_gain[ch] + (1 - self._attack_coeff) * self._current_gain_lin[ch]
                        self._hold_counter = self._hold_samples  # Reset hold counter
                    else:
                        if self._hold_counter > 0: self._hold_counter -= block_samples
                        else: self._current_gain_lin[ch] = self._release_coeff * target_gain[ch] + (1 - self._release_coeff) * self._current_gain_lin[ch]
                    
                    smoothed_gain[ch] = self._current_gain_lin[ch]
                
                output[i:block_end] = block * smoothed_gain[np.newaxis, :]
            
            peak_limit = 0.75
            current_peaks = np.max(np.abs(output), axis=0)
            limit_gain = np.where(current_peaks > peak_limit, peak_limit / np.maximum(current_peaks, 1e-9), 1.0)

            if np.any(limit_gain < 1.0): output *= limit_gain[np.newaxis, :]
            nframe = output.reshape(frame.shape)
            # TODO: Remove debug
            # RNS.log(f"AGC ran in {RNS.prettyshorttime(time.time()-st)}", RNS.LOG_DEBUG)
            return nframe
    
    def _calculate_coefficients(self):
        if self._samplerate:
            self._attack_coeff = 1.0 - np.exp(-1.0 / (self.attack_time * self._samplerate))
            self._release_coeff = 1.0 - np.exp(-1.0 / (self.release_time * self._samplerate))
            self._hold_samples = int(self.hold_time * self._samplerate)
        else:
            self._attack_coeff = 0.1
            self._release_coeff = 0.01
            self._hold_samples = 1000