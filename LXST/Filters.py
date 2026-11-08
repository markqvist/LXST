# Copyright 2024-2026, Mark Qvist

from importlib.util import find_spec
from collections import deque
import numpy as np
import threading
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
        self.paused            = False
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
        if self.paused:     return frame
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

class EchoSuppressor(Filter):
    DEFAULT_MAX_DELAY_MS          = 550
    DEFAULT_TRACK_WINDOW_MS       = 150
    DEFAULT_CORRELATION_FRAME_MS  = 120
    DEFAULT_CORRELATION_THRESHOLD = 0.070
    DEFAULT_RMS_THRESHOLD         = 0.002
    DEFAULT_EMA_ALPHA             = 0.2
    DEFAULT_PREEMPH_ALPHA         = 0.95
    DEFAULT_ACC_FORGET            = 0.92

    DEFAULT_COUPLING_WINDOW_S     = 5.0
    DEFAULT_COUPLING_PERCENTILE   = 15
    DEFAULT_COUPLING_THRESHOLD_DB = -30.0
    DEFAULT_GATE_RATIO_DB         = -3.0
    DEFAULT_CORR_THRESHOLD        = 0.13
    DEFAULT_DTD_ENERGY_DB         = 3.0
    DEFAULT_HANGOVER_MS           = 150
    DEFAULT_ATTACK_MS             = 5
    DEFAULT_RELEASE_MS            = 80
    DEFAULT_REF_RMS_THRESHOLD     = 0.0001
    REQUIRED_COUPLING_HISTORY     = 4
    DEFAULT_ESTIMATE_EVERY_N      = 2

    DEFAULT_CNG_ENABLED           = True
    DEFAULT_CNG_GAIN              = 0.0015
    DEFAULT_CNG_COLOR             = 0.98
    DEFAULT_CNG_BLOCK_SIZE        = 16384

    LOG_INTERVAL_LOCKED           = 0.25
    LOG_INTERVAL_SEARCH           = 0.5
    LOG_INTERVAL_GATE             = 0.25

    def __init__(self, max_delay_ms=DEFAULT_MAX_DELAY_MS, track_window_ms=DEFAULT_TRACK_WINDOW_MS,
                 correlation_frame_ms=DEFAULT_CORRELATION_FRAME_MS, correlation_threshold=DEFAULT_CORRELATION_THRESHOLD,
                 rms_threshold=DEFAULT_RMS_THRESHOLD, ema_alpha=DEFAULT_EMA_ALPHA, preemph_alpha=DEFAULT_PREEMPH_ALPHA,
                 acc_forget=DEFAULT_ACC_FORGET, coupling_window_s=DEFAULT_COUPLING_WINDOW_S,
                 coupling_percentile=DEFAULT_COUPLING_PERCENTILE, coupling_threshold_db=DEFAULT_COUPLING_THRESHOLD_DB,
                 gate_ratio_db=DEFAULT_GATE_RATIO_DB, corr_threshold=DEFAULT_CORR_THRESHOLD, dtd_energy_db=DEFAULT_DTD_ENERGY_DB,
                 hangover_ms=DEFAULT_HANGOVER_MS, attack_ms=DEFAULT_ATTACK_MS, release_ms=DEFAULT_RELEASE_MS,
                 ref_rms_threshold=DEFAULT_REF_RMS_THRESHOLD, estimate_every_n=DEFAULT_ESTIMATE_EVERY_N,
                 cng_enabled=DEFAULT_CNG_ENABLED, cng_gain=DEFAULT_CNG_GAIN, cng_color=DEFAULT_CNG_COLOR):

        super().__init__()

        self.max_delay_ms = max_delay_ms
        self.track_window_ms = track_window_ms
        self.correlation_frame_ms = correlation_frame_ms
        self.correlation_threshold = correlation_threshold
        self.rms_threshold = rms_threshold
        self.ema_alpha = ema_alpha
        self.preemph_alpha = preemph_alpha
        self.acc_forget = acc_forget
        self.estimate_every_n = estimate_every_n
        self.debug_metrics = False

        self.cng_enabled = cng_enabled
        self.cng_gain = cng_gain
        self.cng_color = min(max(float(cng_color), 0.0), 0.999)

        self.coupling_window_s = coupling_window_s
        self.coupling_percentile = coupling_percentile
        self.coupling_threshold_db = coupling_threshold_db
        self.gate_ratio_db = gate_ratio_db
        self.corr_threshold = corr_threshold
        self.dtd_energy_db = dtd_energy_db
        self.hangover_ms = hangover_ms
        self.attack_ms = attack_ms
        self.release_ms = release_ms
        self.ref_rms_threshold = ref_rms_threshold
        self._last_echo_correlation = 0
        self._near_end_active_hold = 0
        self.echo_correlation_window = 1.0
        self.ser_db = 0

        self._lock = threading.Lock()
        self._samplerate = None

        # 48 kHz buffers (gating path)
        self._buffer_size = None
        self._ref_buffer = None
        self._ref_write_pos = 0
        self._ref_valid = 0
        self._max_delay_samples = None
        self._track_window_samples = None
        self._correlation_samples = None

        # Downsampling
        # self._decim_factor = 3
        # self._decim_taps = self._design_decimator_taps(num_taps=12, cutoff_hz=7500, samplerate=48000)
        self._decim_factor = 6
        self._decim_taps = self._design_decimator_taps(num_taps=12, cutoff_hz=3700, samplerate=48000)
        self._decim_state_ref = np.zeros(len(self._decim_taps) - 1, dtype=np.float32)
        self._decim_total_ref = 0
        self._decim_state_mic = np.zeros(len(self._decim_taps) - 1, dtype=np.float32)
        self._decim_total_mic = 0

        # Comfort noise generator
        self._cng_buffer = np.array([], dtype=np.float32)
        self._cng_buffer_pos = 0
        self._cng_state = 0.0
        self._cng_block_size = self.DEFAULT_CNG_BLOCK_SIZE

        # 16 kHz buffers (delay-estimation path)
        self._samplerate_ds = None
        self._buffer_size_ds = None
        self._ref_buffer_ds = None
        self._ref_write_pos_ds = 0
        self._ref_valid_ds = 0
        self._max_delay_samples_ds = None
        self._track_window_samples_ds = None
        self._correlation_samples_ds = None

        # Pre-emphasis states
        self._ref_preemph_state = np.float32(0.0)
        self._mic_preemph_state = np.float32(0.0)
        self._ref_preemph_state_ds = np.float32(0.0)
        self._mic_preemph_state_ds = np.float32(0.0)

        # Mic history (48 kHz unused, kept for API compat; 16 kHz active)
        self._mic_hist = None
        self._mic_hist_write = 0
        self._mic_hist_valid = 0

        self._mic_hist_ds = None
        self._mic_hist_write_ds = 0
        self._mic_hist_valid_ds = 0

        self._corr_acc = None
        self._corr_acc_ds = None

        self._delay_samples = None
        self._delay_ms = None
        self._delay_confidence = 0.0

        self._last_log_time = 0
        self._last_gate_log_time = 0
        self._frame_count = 0

        self._coupling_history = deque(maxlen=10)
        self._coupling = 1e-3
        self._coupling_db = -30.0
        self._disabled_by_coupling = False
        self._current_gain = 1.0
        self._hangover_samples = 0
        self._last_gate_open = True
        self._ser_db_threshold = 11.0
        self._ser_hysterisis = 2
        self._ser_threshold_count = 0

    # Helpers
    @staticmethod
    def _to_mono(frame):
        if frame.ndim == 1: return frame.astype(np.float32, copy=False)
        elif frame.ndim == 2:
            if frame.shape[1] == 1: return frame[:, 0].astype(np.float32, copy=False)
            mono = frame[:, 0].copy()
            mono += frame[:, 1]
            mono *= 0.5
            if mono.dtype != np.float32: return mono.astype(np.float32)
            else:                        return mono
        else: return frame.astype(np.float32, copy=False).ravel()

    # @staticmethod
    # def _to_mono(frame):
    #     if frame.ndim == 1: return frame.astype(np.float32, copy=False)
    #     elif frame.ndim == 2:
    #         if frame.shape[1] == 1: return frame[:, 0].astype(np.float32, copy=False)
    #         return frame.mean(axis=1).astype(np.float32)
    #     else: return frame.astype(np.float32, copy=False).ravel()

    @staticmethod
    def _design_decimator_taps(num_taps=12, cutoff_hz=7500, samplerate=48000):
        n = np.arange(num_taps, dtype=np.float64)
        fc = cutoff_hz / samplerate
        m = n - (num_taps - 1) / 2.0
        h = 2.0 * fc * np.sinc(2.0 * fc * m)
        w = 0.54 - 0.46 * np.cos(2.0 * np.pi * n / (num_taps - 1))
        h = h * w
        h = h / np.sum(h)
        return h.astype(np.float32)

    def _decimate(self, x, state_attr, total_attr):
        x = np.asarray(x, dtype=np.float32)
        if len(x) == 0:
            return np.array([], dtype=np.float32)
        L = len(self._decim_taps)
        state = getattr(self, state_attr)
        total = getattr(self, total_attr)
        buf = np.concatenate((state, x))
        y = np.convolve(buf, self._decim_taps, mode='valid')
        m = (-total) % self._decim_factor
        out = y[m::self._decim_factor]
        setattr(self, total_attr, total + len(x))
        setattr(self, state_attr, buf[-(L - 1):].copy())
        return out

    def _preemph(self, x, state):
        if len(x) == 0: return x, state
        y = np.empty_like(x)
        a = np.float32(self.preemph_alpha)
        y[0] = x[0] - a * state
        y[1:] = x[1:] - a * x[:-1]
        return y, x[-1]

    def _generate_cng_block(self, n):
        white = np.random.normal(0, 1, n).astype(np.float32)
        out = np.empty(n, dtype=np.float32)
        s = self._cng_state
        a = self.cng_color
        # Normalise so output RMS ≈ cng_gain regardless of alpha
        scale = self.cng_gain * np.sqrt(max(0.0, 1.0 - a * a))
        for i in range(n):
            s = a * s + white[i]
            out[i] = s * scale
        self._cng_state = s
        return out

    def _get_cng(self, n):
        if self._cng_buffer_pos + n > len(self._cng_buffer):
            self._cng_buffer = self._generate_cng_block(self._cng_block_size)
            self._cng_buffer_pos = 0
        result = self._cng_buffer[self._cng_buffer_pos:self._cng_buffer_pos + n]
        self._cng_buffer_pos += n
        return result

    # Buffer management
    def _ensure_buffer(self, samplerate):
        if self._samplerate != samplerate or self._ref_buffer is None:
            self._samplerate = samplerate
            self._max_delay_samples = int(self.max_delay_ms / 1000.0 * samplerate)
            self._track_window_samples = int(self.track_window_ms / 1000.0 * samplerate)
            self._correlation_samples = int(self.correlation_frame_ms / 1000.0 * samplerate)

            self._buffer_size = self._max_delay_samples + 16384
            self._ref_buffer = np.zeros(self._buffer_size, dtype=np.float32)
            self._ref_write_pos = 0
            self._ref_valid = 0

            self._corr_acc = np.zeros(self._max_delay_samples + 1, dtype=np.float64)
            self._mic_hist = np.zeros(self._correlation_samples, dtype=np.float32)
            self._mic_hist_write = 0
            self._mic_hist_valid = 0

            # 16 kHz path
            self._samplerate_ds = int(samplerate / self._decim_factor)
            self._max_delay_samples_ds = int(self.max_delay_ms / 1000.0 * self._samplerate_ds)
            self._track_window_samples_ds = int(self.track_window_ms / 1000.0 * self._samplerate_ds)
            self._correlation_samples_ds = int(self.correlation_frame_ms / 1000.0 * self._samplerate_ds)

            self._buffer_size_ds = self._max_delay_samples_ds + 4096
            self._ref_buffer_ds = np.zeros(self._buffer_size_ds, dtype=np.float32)
            self._ref_write_pos_ds = 0
            self._ref_valid_ds = 0

            self._corr_acc_ds = np.zeros(self._max_delay_samples_ds + 1, dtype=np.float64)
            self._mic_hist_ds = np.zeros(self._correlation_samples_ds, dtype=np.float32)
            self._mic_hist_write_ds = 0
            self._mic_hist_valid_ds = 0

            # Reset decimator states
            self._decim_state_ref = np.zeros(len(self._decim_taps) - 1, dtype=np.float32)
            self._decim_total_ref = 0
            self._decim_state_mic = np.zeros(len(self._decim_taps) - 1, dtype=np.float32)
            self._decim_total_mic = 0
            self._ref_preemph_state_ds = np.float32(0.0)
            self._mic_preemph_state_ds = np.float32(0.0)

            self._coupling_history.clear()
            self._coupling = 1e-3
            self._coupling_db = -30.0
            self._disabled_by_coupling = False
            self._current_gain = 1.0
            self._hangover_samples = 0
            self._last_gate_open = True

            RNS.log(f"EchoSuppressor initialised: max_delay={self.max_delay_ms}ms, "
                    f"corr_window={self.correlation_frame_ms}ms, threshold={self.correlation_threshold}, "
                    f"coupling_th={self.coupling_threshold_db}dB, gate_ratio={self.gate_ratio_db}dB, "
                    f"DTD={self.dtd_energy_db}dB, hangover={self.hangover_ms}ms, "
                    f"attack={self.attack_ms}ms, release={self.release_ms}ms, "
                    f"est_rate=1/{self.estimate_every_n}, ds={self._samplerate_ds}Hz, @ {samplerate}Hz",
                    RNS.LOG_DEBUG)

    def _append_reference(self, mono):
        N = len(mono)
        if N > self._buffer_size:
            mono = mono[-self._buffer_size:]
            N = self._buffer_size
        end = self._ref_write_pos + N

        if end <= self._buffer_size: self._ref_buffer[self._ref_write_pos:end] = mono
        else:
            part1 = self._buffer_size - self._ref_write_pos
            self._ref_buffer[self._ref_write_pos:] = mono[:part1]
            self._ref_buffer[:end - self._buffer_size] = mono[part1:]

        self._ref_write_pos = end % self._buffer_size
        self._ref_valid = min(self._ref_valid + N, self._buffer_size)

    def _append_reference_ds(self, mono):
        N = len(mono)
        if N > self._buffer_size_ds:
            mono = mono[-self._buffer_size_ds:]
            N = self._buffer_size_ds
        end = self._ref_write_pos_ds + N

        if end <= self._buffer_size_ds: self._ref_buffer_ds[self._ref_write_pos_ds:end] = mono
        else:
            part1 = self._buffer_size_ds - self._ref_write_pos_ds
            self._ref_buffer_ds[self._ref_write_pos_ds:] = mono[:part1]
            self._ref_buffer_ds[:end - self._buffer_size_ds] = mono[part1:]

        self._ref_write_pos_ds = end % self._buffer_size_ds
        self._ref_valid_ds = min(self._ref_valid_ds + N, self._buffer_size_ds)

    def _append_mic_history(self, mono):
        N = len(mono)
        if N >= self._correlation_samples:
            self._mic_hist[:] = mono[-self._correlation_samples:]
            self._mic_hist_write = 0
            self._mic_hist_valid = self._correlation_samples
            return

        end = self._mic_hist_write + N
        if end <= self._correlation_samples: self._mic_hist[self._mic_hist_write:end] = mono
        else:
            part1 = self._correlation_samples - self._mic_hist_write
            self._mic_hist[self._mic_hist_write:] = mono[:part1]
            self._mic_hist[:end - self._correlation_samples] = mono[part1:]

        self._mic_hist_write = end % self._correlation_samples
        self._mic_hist_valid = min(self._mic_hist_valid + N, self._correlation_samples)

    def _append_mic_history_ds(self, mono):
        N = len(mono)
        if N >= self._correlation_samples_ds:
            self._mic_hist_ds[:] = mono[-self._correlation_samples_ds:]
            self._mic_hist_write_ds = 0
            self._mic_hist_valid_ds = self._correlation_samples_ds
            return

        end = self._mic_hist_write_ds + N
        if end <= self._correlation_samples_ds: self._mic_hist_ds[self._mic_hist_write_ds:end] = mono
        else:
            part1 = self._correlation_samples_ds - self._mic_hist_write_ds
            self._mic_hist_ds[self._mic_hist_write_ds:] = mono[:part1]
            self._mic_hist_ds[:end - self._correlation_samples_ds] = mono[part1:]

        self._mic_hist_write_ds = end % self._correlation_samples_ds
        self._mic_hist_valid_ds = min(self._mic_hist_valid_ds + N, self._correlation_samples_ds)

    def _get_reference_window(self, length):
        length = min(length, self._ref_valid)
        if length <= 0: return np.array([], dtype=np.float32)
        start = (self._ref_write_pos - length) % self._buffer_size
        end = self._ref_write_pos
        if start < end: return self._ref_buffer[start:end].copy()
        else: return np.concatenate( (self._ref_buffer[start:].copy(), self._ref_buffer[:end].copy()) )

    def _get_reference_window_ds(self, length):
        length = min(length, self._ref_valid_ds)
        if length <= 0: return np.array([], dtype=np.float32)
        start = (self._ref_write_pos_ds - length) % self._buffer_size_ds
        end = self._ref_write_pos_ds
        if start < end: return self._ref_buffer_ds[start:end].copy()
        else: return np.concatenate( (self._ref_buffer_ds[start:].copy(), self._ref_buffer_ds[:end].copy()) )

    def _get_delayed_reference(self, delay_samples, length):
        if delay_samples + length > self._ref_valid: return None
        start = (self._ref_write_pos - delay_samples - length) % self._buffer_size
        end = (self._ref_write_pos - delay_samples) % self._buffer_size
        if start < end: return self._ref_buffer[start:end]
        else: return np.concatenate( (self._ref_buffer[start:], self._ref_buffer[:end]) )

    def _get_mic_history(self):
        length = min(self._mic_hist_valid, self._correlation_samples)
        if length <= 0: return np.array([], dtype=np.float32)
        start = (self._mic_hist_write - length) % self._correlation_samples
        end = self._mic_hist_write
        if start < end: return self._mic_hist[start:end].copy()
        else: return np.concatenate( (self._mic_hist[start:].copy(), self._mic_hist[:end].copy()) )

    def _get_mic_history_ds(self):
        length = min(self._mic_hist_valid_ds, self._correlation_samples_ds)
        if length <= 0: return np.array([], dtype=np.float32)
        start = (self._mic_hist_write_ds - length) % self._correlation_samples_ds
        end = self._mic_hist_write_ds
        if start < end: return self._mic_hist_ds[start:end].copy()
        else: return np.concatenate( (self._mic_hist_ds[start:].copy(), self._mic_hist_ds[:end].copy()) )

    # Coupling estimation
    def _update_coupling(self, mic_energy, ref_energy, corr):
        mic_energy_threshold = 6e-7
        ref_energy_threshold = 6e-7
        in_bootstrap = len(self._coupling_history) < self.REQUIRED_COUPLING_HISTORY

        if (ref_energy > ref_energy_threshold and corr > self.corr_threshold and mic_energy > mic_energy_threshold):
            ratio = mic_energy / ref_energy
            self._coupling_history.append(ratio)

            if len(self._coupling_history) >= self.REQUIRED_COUPLING_HISTORY:
                self._coupling = np.percentile(np.array(self._coupling_history, dtype=np.float64), self.coupling_percentile)
                self._coupling_db = 10.0 * np.log10(self._coupling + 1e-12)

                if   self._coupling_db < self.coupling_threshold_db:       self._disabled_by_coupling = True
                elif self._coupling_db > self.coupling_threshold_db + 1.5: self._disabled_by_coupling = False

    # Public interface
    def handle_reference(self, frame, samplerate):
        # st = time.time()
        mono = self._to_mono(frame)
        # RNS.log(f"Ref mono (dtype={frame.dtype}, ndim={frame.ndim}, frame.shape[1]={frame.shape[1]}) conversion in {RNS.prettyshorttime(time.time()-st)}", RNS.LOG_DEBUG)

        # 16 kHz path: downsample raw, then pre-emphasise
        mono_ds = self._decimate(mono, '_decim_state_ref', '_decim_total_ref')
        if len(mono_ds) > 0:
            mono_ds, self._ref_preemph_state_ds = self._preemph(mono_ds, self._ref_preemph_state_ds)

        # 48 kHz path: pre-emphasise
        mono, self._ref_preemph_state = self._preemph(mono, self._ref_preemph_state)

        with self._lock:
            self._ensure_buffer(samplerate)
            self._append_reference(mono)
            if len(mono_ds) > 0:
                self._append_reference_ds(mono_ds)

    def handle_frame(self, frame, samplerate):
        st = time.time()

        original_shape = frame.shape
        mono_raw = self._to_mono(frame)
        N = len(mono_raw)
        if N == 0: return frame

        # mic_rms = np.sqrt(np.mean(mono_raw ** 2))      # TODO: Remove and clean
        # if mic_rms < self.rms_threshold: return frame

        # RNS.log(f"Mono conversion (dtype={frame.dtype}, ndim={frame.ndim}, frame.shape[1]={frame.shape[1]}) in {RNS.prettyshorttime(time.time()-st)}", RNS.LOG_DEBUG)
        # dst = time.time()

        # Downsample for delay estimation
        mono_ds = self._decimate(mono_raw, '_decim_state_mic', '_decim_total_mic')
        # RNS.log(f"Decimation in {RNS.prettyshorttime(time.time()-dst)}", RNS.LOG_DEBUG)
        # pest = time.time()
        
        # Pre-emphasis
        mono_pre, self._mic_preemph_state = self._preemph(mono_raw, self._mic_preemph_state)
        if len(mono_ds) > 0: mono_pre_ds, self._mic_preemph_state_ds = self._preemph(mono_ds, self._mic_preemph_state_ds)
        else:                mono_pre_ds = mono_ds

        # RNS.log(f"Pre-emphasis in {RNS.prettyshorttime(time.time()-pest)}", RNS.LOG_DEBUG)

        # 1. Delay estimation
        self._frame_count += 1
        ref_delayed = None

        if self._ref_valid < N + 100: return frame
        if self._samplerate != samplerate:
            RNS.log(f"EchoSuppressor samplerate mismatch (ref={self._samplerate}, mic={samplerate}), skipping", RNS.LOG_WARNING)
            return frame

        if not (self._frame_count % self.estimate_every_n) == 0:
            with self._lock:
                if len(mono_pre_ds) > 0:
                    self._append_mic_history_ds(mono_pre_ds)
                if self._mic_hist_valid_ds < self._correlation_samples_ds // 2: return frame

        else:
            # pst = time.time()

            with self._lock:
                if len(mono_pre_ds) > 0:
                    self._append_mic_history_ds(mono_pre_ds)
                if self._mic_hist_valid_ds < self._correlation_samples_ds // 2: return frame
                mic_window = self._get_mic_history_ds()
                search_length = min(self._ref_valid_ds, self._max_delay_samples_ds + len(mic_window))
                if search_length <= len(mic_window): return frame
                ref_window = self._get_reference_window_ds(search_length)

            # RNS.log(f"Prep in {RNS.prettyshorttime(time.time()-pst)}", RNS.LOG_DEBUG)
            # fst = time.time()

            # FFT-based cross-correlation at 16 kHz
            M  = len(ref_window)
            Nc = len(mic_window)
            fft_size = 1 << (M + Nc - 1).bit_length()
            C = np.fft.irfft( np.fft.rfft(ref_window, n=fft_size) *
                              np.conj(np.fft.rfft(mic_window, n=fft_size)),
                              n=fft_size )
            c = C[:M - Nc + 1]

            # RNS.log(f"{fft_size} FFT ops in {RNS.prettyshorttime(time.time()-fst)}", RNS.LOG_DEBUG)
            # nst = time.time()

            mic_norm = np.linalg.norm(mic_window)
            if mic_norm == 0: return frame

            ref_cumsum = np.empty(len(ref_window) + 1, dtype=np.float64)
            ref_cumsum[0] = 0.0
            np.multiply(ref_window, ref_window, out=ref_cumsum[1:])
            np.cumsum(ref_cumsum[1:], out=ref_cumsum[1:])
            window_norms = np.sqrt(ref_cumsum[Nc:] - ref_cumsum[:-Nc])

            with np.errstate(divide='ignore', invalid='ignore'): corr = c / (mic_norm * window_norms)
            corr[window_norms == 0] = 0
            abs_corr = np.abs(corr)

            # RNS.log(f"Correlation in {RNS.prettyshorttime(time.time()-nst)}", RNS.LOG_DEBUG)
            # ast = time.time()

            # Accumulate
            self._corr_acc_ds *= self.acc_forget
            self._corr_acc_ds[:len(abs_corr)] += abs_corr[::-1]
            acc_norm = self._corr_acc_ds * (1.0 - self.acc_forget)

            abs_mean = float(np.mean(abs_corr))
            abs_std  = float(np.std(abs_corr))

            # RNS.log(f"Accumulation in {RNS.prettyshorttime(time.time()-ast)}", RNS.LOG_DEBUG)
            # pst = time.time()

            # Search for peak
            if self._delay_samples is not None:
                # _delay_samples is stored in 48 kHz units; convert to 16 kHz for search window
                d_est_ds = int(round(self._delay_samples / self._decim_factor))
                d_min = max(0, d_est_ds - self._track_window_samples_ds)
                d_max = min(len(acc_norm) - 1, d_est_ds + self._track_window_samples_ds)
                track_acc = acc_norm[d_min:d_max + 1]
                best_local_idx = np.argmax(track_acc)
                best_delay_ds = d_min + best_local_idx
                best_val = float(track_acc[best_local_idx])
                if best_val < self.correlation_threshold:
                    best_delay_ds = int(np.argmax(acc_norm))
                    best_val = float(acc_norm[best_delay_ds])
            else:
                best_delay_ds = int(np.argmax(acc_norm))
                best_val = float(acc_norm[best_delay_ds])

            prominence = (best_val - abs_mean) / (abs_std + 1e-12)
            raw_delay_ms = best_delay_ds / self._samplerate_ds * 1000.0

            # RNS.log(f"Peak search in {RNS.prettyshorttime(time.time()-pst)}", RNS.LOG_DEBUG)
            # rst = time.time()

            if best_val >= self.correlation_threshold:
                if self._delay_samples is None:
                    self._delay_samples = float(best_delay_ds * self._decim_factor)
                    self._delay_ms = raw_delay_ms
                    self._delay_confidence = best_val
                else:
                    self._delay_samples = (self.ema_alpha * best_delay_ds * self._decim_factor +
                                           (1.0 - self.ema_alpha) * self._delay_samples)
                    self._delay_ms = self._delay_samples / self._samplerate * 1000.0
                    self._delay_confidence = (self.ema_alpha * best_val +
                                              (1.0 - self.ema_alpha) * self._delay_confidence)

            # RNS.log(f"Result calc in {RNS.prettyshorttime(time.time()-rst)}", RNS.LOG_DEBUG)

        # Fetch delayed reference aligned with current mic frame (48 kHz)
        if self._delay_samples is not None:
            int_delay = int(round(self._delay_samples))
            ref_delayed = self._get_delayed_reference(int_delay, N)

        # RNS.log(f"Total delay estimation in {RNS.prettyshorttime(time.time()-st)}", RNS.LOG_DEBUG) # TODO: Remove

        # 2. Echo detection and gating
        if ref_delayed is None or len(ref_delayed) != N: return frame

        # Energy on pre-emphasised signals
        mic_energy  = np.mean(mono_pre ** 2)
        ref_energy  = np.mean(ref_delayed ** 2)

        # Normalised correlation
        mic_norm = np.linalg.norm(mono_pre)
        ref_norm = np.linalg.norm(ref_delayed)
        if mic_norm > 1e-12 and ref_norm > 1e-12: corr = abs(np.dot(mono_pre, ref_delayed) / (mic_norm * ref_norm))
        else:                                     corr = 0.0

        # Predicted echo energy from current coupling estimate
        now = time.time()
        predicted_echo_energy = self._coupling * ref_energy

        if corr > self.corr_threshold: self._last_echo_correlation = time.time()
        echo_correlated = now < self._last_echo_correlation + self.echo_correlation_window

        if mic_energy > 2e-6:
            try: self.ser_db = 10.0 * np.log10(mic_energy/predicted_echo_energy + 1e-12)
            except Exception as e: RNS.log(f"Numerical error in energy calculation: {e}", RNS.LOG_DEBUG)

        # Near-end energy estimate (residual after predicted echo)
        near_energy = max(0.0, mic_energy - predicted_echo_energy)

        # Determine near-end activity
        near_end_active = False
        in_bootstrap = len(self._coupling_history) < self.REQUIRED_COUPLING_HISTORY
        if   self._near_end_active_hold > now: near_end_active = True
        elif in_bootstrap: near_end_active = near_energy > 2e-6 and corr < self.corr_threshold
        else:
            if now > self._last_echo_correlation + self.echo_correlation_window: near_end_active = True
            if self.ser_db > self._ser_db_threshold:
                self._ser_threshold_count += 1
                if self._ser_threshold_count >= self._ser_hysterisis:
                    near_end_active = True
                    self._near_end_active_hold = now+0.75
            else: self._ser_threshold_count = 0

        # Update coupling estimate
        if time.time() < self._last_echo_correlation + self.echo_correlation_window: self._update_coupling(mic_energy, ref_energy, corr)
        if self._disabled_by_coupling: return frame
        if len(self._coupling_history) < self.REQUIRED_COUPLING_HISTORY: return frame

        # RNS.log(f"nA: {near_end_active}, coupling_db: {self._coupling_db}, eE: {predicted_echo_energy*1e7}, nE: {near_energy*1e7}")

        should_gate = echo_correlated and not near_end_active

        # Gain smoothing
        frame_duration_ms = N / samplerate * 1000.0
        attack_coeff = 1.0 - np.exp(-frame_duration_ms / self.attack_ms)
        release_coeff = 1.0 - np.exp(-frame_duration_ms / self.release_ms)

        if near_end_active:
            target_gain = 1.0
            self._hangover_samples = 0
        elif should_gate:
            target_gain = 0.0
            self._hangover_samples = int(self.hangover_ms / 1000.0 * samplerate)
        elif self._hangover_samples > 0:
            target_gain = 0.0
            self._hangover_samples -= N
        else:
            target_gain = 1.0

        coeff = attack_coeff if target_gain < self._current_gain else release_coeff
        self._current_gain += (target_gain - self._current_gain) * coeff

        if self._current_gain < 1e-6:  self._current_gain = 0.0
        elif self._current_gain > 1.0: self._current_gain = 1.0

        if len(original_shape) == 1: output = mono_raw * self._current_gain
        else:                        output = frame * self._current_gain

        # Comfort noise injection when gated
        if self.cng_enabled and self._current_gain < 0.05:
            cng = self._get_cng(output.shape[0])
            if len(original_shape) == 1:
                output = output + cng
            else:
                output = output + cng[:, np.newaxis]
                output = np.clip(output, -1.0, 1.0)

        if self.debug_metrics: RNS.log(f"GT: {self._current_gain < 0.5}, nA: {near_end_active}, EC: {echo_correlated}, SER: {round(self.ser_db,2)} dB, coupling: {round(self._coupling_db,2)} dB, finish {RNS.prettyshorttime(time.time()-st)}", RNS.LOG_DEBUG)

        return output

    @property
    def delay_ms(self): return self._delay_ms

    @property
    def delay_samples(self): return self._delay_samples

    @property
    def confidence(self): return self._delay_confidence

    @property
    def coupling_db(self): return self._coupling_db

    @property
    def gain(self): return self._current_gain

# class EchoCanceller(Filter):
#     # Delay estimator defaults
#     DEFAULT_MAX_DELAY_MS          = 1000
#     DEFAULT_TRACK_WINDOW_MS       = 150
#     DEFAULT_CORRELATION_FRAME_MS  = 120
#     DEFAULT_CORRELATION_THRESHOLD = 0.070
#     DEFAULT_RMS_THRESHOLD         = 0.002
#     DEFAULT_EMA_ALPHA             = 0.2
#     DEFAULT_PREEMPH_ALPHA         = 0.95
#     DEFAULT_ACC_FORGET            = 0.92

#     # NLMS defaults
#     DEFAULT_FILTER_TAPS           = 4096
#     DEFAULT_NLMS_MU               = 0.8
#     DEFAULT_NLMS_EPS              = 1e-12
#     DEFAULT_LEAKAGE               = 0.9999

#     # Double-talk detection defaults
#     DEFAULT_DTD_THRESHOLD         = 5.0          # hard freeze threshold, linear (~9.5 dB)
#     DEFAULT_DTD_HANGOVER_MS       = 300          # keep frozen for N ms after trigger
#     DEFAULT_SOFT_DTD_THRESHOLD    = 2.5          # soft freeze threshold, linear (~3.5 dB)
#     DEFAULT_SOFT_DTD_MU_SCALE     = 0.3          # mu multiplier when in soft freeze

#     # Post-filter defaults
#     DEFAULT_PF_ENABLE             = True
#     DEFAULT_PF_FFT_SIZE           = 256
#     DEFAULT_PF_HOP_SIZE           = 128
#     DEFAULT_PF_ALPHA              = 12.0         # over-subtraction factor (1.0 = Wiener)
#     DEFAULT_PF_BETA               = 0.0001       # spectral floor
#     DEFAULT_PF_SMOOTH             = 0.5          # power smoothing coeff
#     DEFAULT_PF_ALPHA_SOFT         = 0.8          # reduced aggression in soft freeze
#     DEFAULT_PF_ALPHA_HARD         = 0.5          # minimal aggression in hard freeze

#     # Logging
#     LOG_INTERVAL_LOCKED           = 0.25
#     LOG_INTERVAL_SEARCH           = 0.5
#     PF_LOG_INTERVAL               = 0.2          # post-filter debug output interval

#     def __init__(self, max_delay_ms=DEFAULT_MAX_DELAY_MS, track_window_ms=DEFAULT_TRACK_WINDOW_MS,
#                  correlation_frame_ms=DEFAULT_CORRELATION_FRAME_MS, correlation_threshold=DEFAULT_CORRELATION_THRESHOLD,
#                  rms_threshold=DEFAULT_RMS_THRESHOLD, ema_alpha=DEFAULT_EMA_ALPHA, preemph_alpha=DEFAULT_PREEMPH_ALPHA,
#                  acc_forget=DEFAULT_ACC_FORGET, filter_taps=DEFAULT_FILTER_TAPS, nlms_mu=DEFAULT_NLMS_MU, nlms_eps=DEFAULT_NLMS_EPS,
#                  leakage=DEFAULT_LEAKAGE, dtd_threshold=DEFAULT_DTD_THRESHOLD, dtd_hangover_ms=DEFAULT_DTD_HANGOVER_MS,
#                  soft_dtd_threshold=DEFAULT_SOFT_DTD_THRESHOLD, soft_dtd_mu_scale=DEFAULT_SOFT_DTD_MU_SCALE,
#                  pf_enable=DEFAULT_PF_ENABLE, pf_fft_size=DEFAULT_PF_FFT_SIZE, pf_hop_size=DEFAULT_PF_HOP_SIZE,
#                  pf_alpha=DEFAULT_PF_ALPHA, pf_beta=DEFAULT_PF_BETA, pf_smooth=DEFAULT_PF_SMOOTH,
#                  pf_alpha_soft=DEFAULT_PF_ALPHA_SOFT, pf_alpha_hard=DEFAULT_PF_ALPHA_HARD):
        
#         super().__init__()

#         # Delay estimator parameters
#         self.max_delay_ms = max_delay_ms
#         self.track_window_ms = track_window_ms
#         self.correlation_frame_ms = correlation_frame_ms
#         self.correlation_threshold = correlation_threshold
#         self.rms_threshold = rms_threshold
#         self.ema_alpha = ema_alpha
#         self.preemph_alpha = preemph_alpha
#         self.acc_forget = acc_forget

#         # NLMS parameters
#         self.filter_taps = filter_taps
#         self.nlms_mu = nlms_mu
#         self.nlms_eps = nlms_eps
#         self.leakage = leakage
#         self.dtd_threshold = dtd_threshold
#         self.dtd_hangover_ms = dtd_hangover_ms
#         self.soft_dtd_threshold = soft_dtd_threshold
#         self.soft_dtd_mu_scale = soft_dtd_mu_scale

#         # Post-filter parameters
#         self.pf_enable = pf_enable
#         self.pf_fft_size = pf_fft_size
#         self.pf_hop_size = pf_hop_size
#         self.pf_alpha = pf_alpha
#         self.pf_beta = pf_beta
#         self.pf_smooth = pf_smooth
#         self.pf_alpha_soft = pf_alpha_soft
#         self.pf_alpha_hard = pf_alpha_hard

#         # Threading / state
#         self._lock = threading.Lock()
#         self._samplerate = None

#         # Reference ring buffer (pre-emphasised)
#         self._buffer_size = None
#         self._ref_buffer = None
#         self._ref_write_pos = 0
#         self._ref_valid = 0
#         self._max_delay_samples = None
#         self._track_window_samples = None
#         self._correlation_samples = None

#         # Pre-emphasis / de-emphasis states
#         self._ref_preemph_state = np.float32(0.0)
#         self._mic_preemph_state = np.float32(0.0)
#         self._deemph_state = np.float32(0.0)

#         # Mic history for delay estimation
#         self._mic_hist = None
#         self._mic_hist_write = 0
#         self._mic_hist_valid = 0

#         # Delay accumulator
#         self._corr_acc = None

#         # NLMS coefficients
#         self._w = None

#         # Delay estimate
#         self._delay_samples = None
#         self._delay_ms = None
#         self._delay_confidence = 0.0

#         # Logging / counters
#         self._last_log_time = 0
#         self._frame_count = 0

#         # Double-talk state
#         self._dtd_hangover_counter = 0
#         self._dtd_was_frozen = False

#         # Post-filter state
#         self._pf_inbuf = None
#         self._pf_ecbuf = None
#         self._pf_outbuf = None
#         self._pf_synbuf = None
#         self._pf_window = None
#         self._pf_echo_power = None
#         self._pf_res_power = None

#         # Post-filter debug accumulator
#         self._pf_last_debug_time = 0
#         self._pf_debug_frames = 0
#         self._pf_debug_acc = None

#     # Helpers
#     @staticmethod
#     def _to_mono(frame):
#         if frame.ndim == 1: return frame.astype(np.float32, copy=False)
#         elif frame.ndim == 2:
#             if frame.shape[1] == 1: return frame[:, 0].astype(np.float32, copy=False)
#             return frame.mean(axis=1).astype(np.float32)
#         else: return frame.astype(np.float32, copy=False).ravel()

#     def _preemph(self, x, state):
#         # First-order pre-emphasis filter
#         y = np.empty_like(x)
#         a = np.float32(self.preemph_alpha)
#         y[0] = x[0] - a * state
#         y[1:] = x[1:] - a * x[:-1]
#         return y, x[-1]

#     def _deemph(self, x, state):
#         # Inverse of pre-emphasis
#         y = np.empty_like(x)
#         a = np.float32(self.preemph_alpha)
#         y[0] = x[0] + a * state
#         for i in range(1, len(x)):
#             y[i] = x[i] + a * y[i - 1]
#         return y, y[-1]

#     def _ensure_buffer(self, samplerate):
#         if self._samplerate != samplerate or self._ref_buffer is None:
#             self._samplerate = samplerate
#             self._max_delay_samples = int(self.max_delay_ms / 1000.0 * samplerate)
#             self._track_window_samples = int(self.track_window_ms / 1000.0 * samplerate)
#             self._correlation_samples = int(self.correlation_frame_ms / 1000.0 * samplerate)

#             # Reference buffer: max delay + margin
#             self._buffer_size = self._max_delay_samples + 16384
#             self._ref_buffer = np.zeros(self._buffer_size, dtype=np.float32)
#             self._ref_write_pos = 0
#             self._ref_valid = 0

#             self._corr_acc = np.zeros(self._max_delay_samples + 1, dtype=np.float64)
#             self._mic_hist = np.zeros(self._correlation_samples, dtype=np.float32)
#             self._mic_hist_write = 0
#             self._mic_hist_valid = 0

#             self._w = np.zeros(self.filter_taps, dtype=np.float32)

#             # Post-filter state
#             if self.pf_enable:
#                 self._pf_inbuf = []
#                 self._pf_ecbuf = []
#                 self._pf_outbuf = []
#                 self._pf_synbuf = np.zeros(self.pf_fft_size, dtype=np.float32)
#                 self._pf_window = np.sqrt(np.hanning(self.pf_fft_size)).astype(np.float32)
#                 half_bins = self.pf_fft_size // 2 + 1
#                 self._pf_echo_power = np.zeros(half_bins, dtype=np.float64)
#                 self._pf_res_power = np.zeros(half_bins, dtype=np.float64)

#             # Debug accumulator
#             self._pf_last_debug_time = 0
#             self._pf_debug_frames = 0
#             self._pf_debug_acc = { 'nlms_pre': 0.0, 'nlms_out': 0.0, 'total_out': 0.0,
#                                    'gain_mean': 0.0, 'gain_min': 0.0, 'floor_pct': 0.0,
#                                    'ratio_mean_db': 0.0, 'ratio_max_db': 0.0,
#                                    'power_echo_db': 0.0, 'power_res_db': 0.0 }

#             pf_info = f", post-filter={self.pf_fft_size}/{self.pf_hop_size}" if self.pf_enable else ", post-filter=off"
#             RNS.log(f"EchoCanceller initialised: max_delay={self.max_delay_ms}ms, "
#                     f"corr_window={self.correlation_frame_ms}ms, taps={self.filter_taps}, "
#                     f"mu={self.nlms_mu}, threshold={self.correlation_threshold}, "
#                     f"DTD_hard={self.dtd_threshold}dB({20*np.log10(self.dtd_threshold):.1f}), "
#                     f"DTD_soft={self.soft_dtd_threshold}dB({20*np.log10(self.soft_dtd_threshold):.1f}), "
#                     f"hangover={self.dtd_hangover_ms}ms{pf_info}, @ {samplerate}Hz",
#                     RNS.LOG_DEBUG)

#     def _append_reference(self, mono):
#         N = len(mono)
#         if N > self._buffer_size:
#             mono = mono[-self._buffer_size:]
#             N = self._buffer_size
#         end = self._ref_write_pos + N
        
#         if end <= self._buffer_size: self._ref_buffer[self._ref_write_pos:end] = mono
#         else:
#             part1 = self._buffer_size - self._ref_write_pos
#             self._ref_buffer[self._ref_write_pos:] = mono[:part1]
#             self._ref_buffer[:end - self._buffer_size] = mono[part1:]
        
#         self._ref_write_pos = end % self._buffer_size
#         self._ref_valid = min(self._ref_valid + N, self._buffer_size)

#     def _append_mic_history(self, mono):
#         N = len(mono)
#         if N >= self._correlation_samples:
#             self._mic_hist[:] = mono[-self._correlation_samples:]
#             self._mic_hist_write = 0
#             self._mic_hist_valid = self._correlation_samples
#             return
        
#         end = self._mic_hist_write + N
#         if end <= self._correlation_samples: self._mic_hist[self._mic_hist_write:end] = mono
#         else:
#             part1 = self._correlation_samples - self._mic_hist_write
#             self._mic_hist[self._mic_hist_write:] = mono[:part1]
#             self._mic_hist[:end - self._correlation_samples] = mono[part1:]
        
#         self._mic_hist_write = end % self._correlation_samples
#         self._mic_hist_valid = min(self._mic_hist_valid + N, self._correlation_samples)

#     def _get_reference_window(self, length):
#         length = min(length, self._ref_valid)
#         if length <= 0: return np.array([], dtype=np.float32)
#         start = (self._ref_write_pos - length) % self._buffer_size
#         end = self._ref_write_pos
#         if start < end: return self._ref_buffer[start:end].copy()
#         else:           return np.concatenate( (self._ref_buffer[start:].copy(), self._ref_buffer[:end].copy()) )

#     def _get_mic_history(self):
#         length = min(self._mic_hist_valid, self._correlation_samples)
#         if length <= 0: return np.array([], dtype=np.float32)
#         start = (self._mic_hist_write - length) % self._correlation_samples
#         end = self._mic_hist_write
#         if start < end: return self._mic_hist[start:end].copy()
#         else:           return np.concatenate( (self._mic_hist[start:].copy(), self._mic_hist[:end].copy()) )

#     # Post-filter
#     def _pf_process(self, residual, echo_estimate, alpha):
#         # STFT overlap-add power-subtraction post-filter
#         #
#         # Operates in the time domain after de-emphasis so that
#         # suppression is not undone by the de-emphasis IIR.
#         #
#         # Uses the gain rule::
#         #
#         #     G = max( 1 - alpha * P_echo / P_res , beta )
#         #
#         # where *P_res* is the smoothed power of the residual and
#         # *P_echo* the smoothed power of the echo estimate. Returns
#         # the filtered time-domain signal and a dict of diagnostic stats.

#         N = len(residual)
#         self._pf_inbuf.extend(residual)
#         self._pf_ecbuf.extend(echo_estimate)

#         fft_size = self.pf_fft_size
#         hop = self.pf_hop_size
#         window = self._pf_window
#         synbuf = self._pf_synbuf
#         outbuf = self._pf_outbuf

#         block_stats = []

#         while len(self._pf_inbuf) >= fft_size:
#             x = np.array(self._pf_inbuf[:fft_size], dtype=np.float32) * window
#             e = np.array(self._pf_ecbuf[:fft_size], dtype=np.float32) * window

#             X = np.fft.rfft(x)
#             E = np.fft.rfft(e)

#             absX2 = np.abs(X) ** 2
#             absE2 = np.abs(E) ** 2

#             self._pf_res_power = self.pf_smooth * self._pf_res_power + (1.0 - self.pf_smooth) * absX2
#             self._pf_echo_power = self.pf_smooth * self._pf_echo_power + (1.0 - self.pf_smooth) * absE2

#             # Classic power-subtraction ratio
#             with np.errstate(divide='ignore', invalid='ignore'):
#                 ratio = self._pf_echo_power / (self._pf_res_power + 1e-12)
#             ratio = np.clip(ratio, 0.0, 1e6)

#             gain = 1.0 - alpha * ratio
#             np.clip(gain, self.pf_beta, 1.0, out=gain)

#             # Collect stats for this block
#             valid_bins = len(gain)
#             floor_count = int(np.sum(gain <= self.pf_beta + 1e-9))
#             block_stats.append( {'gain_mean': float(np.mean(gain)),
#                                  'gain_min': float(np.min(gain)),
#                                  'floor_pct': 100.0 * floor_count / valid_bins,
#                                  'ratio_mean_db': float(10.0 * np.log10(np.mean(ratio) + 1e-12)),
#                                  'ratio_max_db': float(10.0 * np.log10(np.max(ratio) + 1e-12)),
#                                  'power_echo_db': float(10.0 * np.log10(np.mean(self._pf_echo_power) + 1e-12)),
#                                  'power_res_db': float(10.0 * np.log10(np.mean(self._pf_res_power) + 1e-12))} )

#             Y = X * gain
#             y = np.fft.irfft(Y, n=fft_size) * window

#             synbuf += y
#             outbuf.extend(synbuf[:hop].tolist())
#             synbuf[:-hop] = synbuf[hop:]
#             synbuf[-hop:] = 0.0

#             del self._pf_inbuf[:hop]
#             del self._pf_ecbuf[:hop]

#         if len(outbuf) >= N:
#             result = np.array(outbuf[:N], dtype=np.float32)
#             del outbuf[:N]
#             return result, block_stats

#         else:
#             available = len(outbuf)
#             result = np.empty(N, dtype=np.float32)
#             if available > 0:
#                 result[:available] = np.array(outbuf[:available], dtype=np.float32)
#                 del outbuf[:available]
#             result[available:] = residual[available:]
#             return result, block_stats

#     def _pf_flush_debug(self, now, force=False):
#         if self._pf_debug_frames == 0: return
#         if not force and now - self._pf_last_debug_time < self.PF_LOG_INTERVAL: return

#         n = self._pf_debug_frames
#         acc = self._pf_debug_acc
#         RNS.log(f"EchoCanceller PF: "
#                 f"nlms_pre={acc['nlms_pre']/n:.1f}dB "
#                 f"nlms_out={acc['nlms_out']/n:.1f}dB "
#                 f"total_out={acc['total_out']/n:.1f}dB "
#                 f"gain_mean={acc['gain_mean']/n:.3f} "
#                 f"gain_min={acc['gain_min']/n:.3f} "
#                 f"floor_pct={acc['floor_pct']/n:.1f}% "
#                 f"ratio_mean={acc['ratio_mean_db']/n:.1f}dB "
#                 f"ratio_max={acc['ratio_max_db']/n:.1f}dB "
#                 f"Pecho={acc['power_echo_db']/n:.1f}dB "
#                 f"Pres={acc['power_res_db']/n:.1f}dB "
#                 f"frames={n}",
#                 RNS.LOG_DEBUG)

#         self._pf_last_debug_time = now
#         self._pf_debug_frames = 0
#         for k in acc: acc[k] = 0.0

#     # Public interface
#     def handle_reference(self, frame, samplerate):
#         mono = self._to_mono(frame)
#         mono, self._ref_preemph_state = self._preemph(mono, self._ref_preemph_state)
#         with self._lock:
#             self._ensure_buffer(samplerate)
#             self._append_reference(mono)

#     def handle_frame(self, frame, samplerate):
#         original_shape = frame.shape
#         mono = self._to_mono(frame)
#         N = len(mono)
#         if N == 0: return frame

#         mic_rms = np.sqrt(np.mean(mono ** 2))
#         if mic_rms < self.rms_threshold: return frame

#         # Pre-emphasise mic for both delay estimation and NLMS
#         mono_pre, self._mic_preemph_state = self._preemph(mono, self._mic_preemph_state)

#         # 1. Delay estimation
#         seg = None
#         with self._lock:
#             if self._ref_valid < N + 100: return frame
#             if self._samplerate != samplerate:
#                 RNS.log(f"EchoCanceller samplerate mismatch (ref={self._samplerate}, mic={samplerate}), skipping", RNS.LOG_WARNING)
#                 return frame

#             # Accumulate history
#             self._append_mic_history(mono_pre)
#             if self._mic_hist_valid < self._correlation_samples // 2: return frame

#             mic_window = self._get_mic_history()
#             search_length = min(self._ref_valid, self._max_delay_samples + len(mic_window))
#             if search_length <= len(mic_window): return frame
#             ref_window = self._get_reference_window(search_length)

#             # FFT-based cross-correlation
#             M = len(ref_window)
#             Nc = len(mic_window)
#             fft_size = 1 << (M + Nc - 1).bit_length()
#             C = np.fft.irfft( np.fft.rfft(ref_window, n=fft_size) *
#                               np.conj(np.fft.rfft(mic_window, n=fft_size)),
#                               n=fft_size )
#             c = C[:M - Nc + 1]

#             mic_norm = np.linalg.norm(mic_window)
#             if mic_norm == 0: return frame

#             ref_sq = ref_window ** 2
#             ref_cumsum = np.concatenate(([0.0], np.cumsum(ref_sq, dtype=np.float64)))
#             window_norms = np.sqrt(ref_cumsum[Nc:] - ref_cumsum[:-Nc])

#             with np.errstate(divide='ignore', invalid='ignore'): corr = c / (mic_norm * window_norms)
#             corr[window_norms == 0] = 0
#             abs_corr = np.abs(corr)

#             # Accumulate
#             self._corr_acc *= self.acc_forget
#             self._corr_acc[:len(abs_corr)] += abs_corr[::-1]
#             acc_norm = self._corr_acc * (1.0 - self.acc_forget)

#             # Statistics for logging
#             abs_mean = float(np.mean(abs_corr))
#             abs_std = float(np.std(abs_corr))

#             # Search for peak
#             if self._delay_samples is not None:
#                 d_est = int(round(self._delay_samples))
#                 d_min = max(0, d_est - self._track_window_samples)
#                 d_max = min(len(acc_norm) - 1, d_est + self._track_window_samples)
#                 track_acc = acc_norm[d_min:d_max + 1]
#                 best_local_idx = np.argmax(track_acc)
#                 best_delay = d_min + best_local_idx
#                 best_val = float(track_acc[best_local_idx])
#                 if best_val < self.correlation_threshold:
#                     best_delay = int(np.argmax(acc_norm))
#                     best_val = float(acc_norm[best_delay])
#             else:
#                 best_delay = int(np.argmax(acc_norm))
#                 best_val = float(acc_norm[best_delay])

#             prominence = (best_val - abs_mean) / (abs_std + 1e-12)
#             raw_delay_ms = best_delay / self._samplerate * 1000.0
#             self._frame_count += 1
#             now = time.time()

#             if best_val >= self.correlation_threshold:
#                 if self._delay_samples is None:
#                     self._delay_samples = float(best_delay)
#                     self._delay_ms = raw_delay_ms
#                     self._delay_confidence = best_val
#                 else:
#                     self._delay_samples = ( self.ema_alpha * best_delay + (1.0 - self.ema_alpha) * self._delay_samples )
#                     self._delay_ms = self._delay_samples / self._samplerate * 1000.0
#                     self._delay_confidence = ( self.ema_alpha * best_val + (1.0 - self.ema_alpha) * self._delay_confidence )

#             #     if (now - self._last_log_time > self.LOG_INTERVAL_LOCKED or abs(raw_delay_ms - self._delay_ms) > 5):
#             #         RNS.log(f"EchoCanceller delay estimate: {self._delay_ms:.1f} ms "
#             #                 f"(confidence={self._delay_confidence:.3f}, "
#             #                 f"raw={raw_delay_ms:.1f} ms, val={best_val:.4f}, "
#             #                 f"prom={prominence:.1f})",
#             #                 RNS.LOG_DEBUG)
#             #         self._last_log_time = now
#             # else:
#             #     if (self._delay_samples is None and (self._frame_count % 3 == 0 or now - self._last_log_time > self.LOG_INTERVAL_SEARCH)):
#             #         RNS.log(f"EchoCanceller searching: max={best_val:.4f}, "
#             #                 f"mean={abs_mean:.4f}, std={abs_std:.4f}, "
#             #                 f"prom={prominence:.1f}, peak_delay={raw_delay_ms:.1f}ms, "
#             #                 f"hist_valid={self._mic_hist_valid}",
#             #                 RNS.LOG_DEBUG)
#             #         self._last_log_time = now

#             # Prepare aligned reference segment for NLMS
#             if self._delay_samples is not None:
#                 int_delay = int(round(self._delay_samples))
#                 needed = int_delay + N + self.filter_taps - 1
#                 if self._ref_valid >= needed:
#                     rw = self._get_reference_window(needed)
#                     seg = rw[:N + self.filter_taps - 1]

#         # 2. NLMS adaptive filter
#         if seg is None or len(seg) < N + self.filter_taps - 1: return frame

#         L = self.filter_taps
#         w = self._w
#         mu = self.nlms_mu
#         eps = self.nlms_eps
#         leakage = self.leakage

#         clean_pre = np.empty(N, dtype=np.float32)
#         echo_pre = np.empty(N, dtype=np.float32)

#         # Frame-level double-talk detection
#         ref_aligned = seg[L - 1:L - 1 + N]
#         ref_peak = np.max(np.abs(ref_aligned))
#         mic_peak = np.max(np.abs(mono_pre))
#         ratio = mic_peak / (ref_peak + 1e-12)

#         hard_freeze = ratio > self.dtd_threshold

#         if hard_freeze:
#             self._dtd_hangover_counter = int(self.dtd_hangover_ms / 1000.0 * self._samplerate)
#             freeze = True
#         elif self._dtd_hangover_counter > 0:
#             freeze = True
#             self._dtd_hangover_counter -= N
#         else:
#             freeze = False

#         soft_freeze = (not freeze) and (ratio > self.soft_dtd_threshold)
#         effective_mu = mu * self.soft_dtd_mu_scale if soft_freeze else mu

#         if freeze:        pf_alpha = self.pf_alpha_hard
#         elif soft_freeze: pf_alpha = self.pf_alpha_soft
#         else:             pf_alpha = self.pf_alpha

#         if freeze != self._dtd_was_frozen:
#             state = "frozen" if freeze else "active"
#             RNS.log(f"EchoCanceller DTD {state} (ratio={ratio:.2f}, ref_peak={ref_peak:.4f}, mic_peak={mic_peak:.4f})", RNS.LOG_DEBUG)
#             self._dtd_was_frozen = freeze

#         for i in range(N):
#             x = seg[i:i + L][::-1]
#             y_hat = np.dot(w, x)
#             e = mono_pre[i] - y_hat
#             clean_pre[i] = e
#             echo_pre[i] = y_hat

#             if not freeze:
#                 pw = np.dot(x, x)
#                 w *= leakage
#                 w += effective_mu * e * x / (pw + eps)

#         # 3. De-emphasis
#         clean_raw_nlms, self._deemph_state = self._deemph(clean_pre, self._deemph_state)

#         if self.pf_enable and self._pf_window is not None:
#             echo_time = mono - clean_raw_nlms
#             filtered_raw, block_stats = self._pf_process(clean_raw_nlms, echo_time, pf_alpha)
#         else:
#             filtered_raw = clean_raw_nlms
#             block_stats = []

#         # 4. Frame-level ERLE and spectral diagnostics
#         power_mic = np.mean(mono ** 2)
#         power_nlms = np.mean(clean_raw_nlms ** 2)
#         power_pf = np.mean(filtered_raw ** 2)
#         power_mic_pre = np.mean(mono_pre ** 2)
#         power_nlms_pre = np.mean(clean_pre ** 2)

#         if power_nlms_pre > 1e-18: erle_nlms_pre = 10.0 * np.log10(power_mic_pre / power_nlms_pre)
#         else:                      erle_nlms_pre = 99.0

#         if power_nlms > 1e-18:     erle_nlms_out = 10.0 * np.log10(power_mic / power_nlms)
#         else:                      erle_nlms_out = 99.0

#         if power_pf > 1e-18:       erle_total_out = 10.0 * np.log10(power_mic / power_pf)
#         else:                      erle_total_out = 99.0

#         if block_stats:
#             avg = { 'gain_mean': sum(s['gain_mean'] for s in block_stats) / len(block_stats),
#                     'gain_min': sum(s['gain_min'] for s in block_stats) / len(block_stats),
#                     'floor_pct': sum(s['floor_pct'] for s in block_stats) / len(block_stats),
#                     'ratio_mean_db': sum(s['ratio_mean_db'] for s in block_stats) / len(block_stats),
#                     'ratio_max_db': sum(s['ratio_max_db'] for s in block_stats) / len(block_stats),
#                     'power_echo_db': sum(s['power_echo_db'] for s in block_stats) / len(block_stats),
#                     'power_res_db': sum(s['power_res_db'] for s in block_stats) / len(block_stats) }
#         else:
#             avg = { 'gain_mean': 1.0, 'gain_min': 1.0, 'floor_pct': 0.0, 'ratio_mean_db': -99.0,
#                     'ratio_max_db': -99.0, 'power_echo_db': -99.0, 'power_res_db': -99.0 }

#         acc = self._pf_debug_acc
#         acc['nlms_pre'] += erle_nlms_pre
#         acc['nlms_out'] += erle_nlms_out
#         acc['total_out'] += erle_total_out
#         acc['gain_mean'] += avg['gain_mean']
#         acc['gain_min'] += avg['gain_min']
#         acc['floor_pct'] += avg['floor_pct']
#         acc['ratio_mean_db'] += avg['ratio_mean_db']
#         acc['ratio_max_db'] += avg['ratio_max_db']
#         acc['power_echo_db'] += avg['power_echo_db']
#         acc['power_res_db'] += avg['power_res_db']
#         self._pf_debug_frames += 1

#         now = time.time()
#         self._pf_flush_debug(now)

#         # Compute echo estimate and subtract from original channels
#         echo_mono = mono - filtered_raw
#         if len(original_shape) == 1: output = filtered_raw
#         else:                        output = frame - echo_mono[:, np.newaxis]

#         return output

#     @property
#     def delay_ms(self): return self._delay_ms

#     @property
#     def delay_samples(self): return self._delay_samples

#     @property
#     def confidence(self): return self._delay_confidence
