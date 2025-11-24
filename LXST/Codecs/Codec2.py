import time
import math
import struct
import pycodec2
import numpy as np
from .Codec import Codec, CodecError, resample_bytes

# TODO: Remove debug
import RNS

class Codec2(Codec):
    CODEC2_700C     = 700
    CODEC2_1200     = 1200
    CODEC2_1300     = 1300
    CODEC2_1400     = 1400
    CODEC2_1600     = 1600
    CODEC2_2400     = 2400
    CODEC2_3200     = 3200

    INPUT_RATE      = 8000
    OUTPUT_RATE     = 8000
    FRAME_QUANTA_MS = 40
    TYPE_MAP_FACTOR = np.iinfo("int16").max

    MODE_HEADERS = {CODEC2_700C: 0x00,
                    CODEC2_1200: 0x01,
                    CODEC2_1300: 0x02,
                    CODEC2_1400: 0x03,
                    CODEC2_1600: 0x04,
                    CODEC2_2400: 0x05,
                    CODEC2_3200: 0x06}

    HEADER_MODES = {0x00: CODEC2_700C,
                    0x01: CODEC2_1200,
                    0x02: CODEC2_1300,
                    0x03: CODEC2_1400,
                    0x04: CODEC2_1600,
                    0x05: CODEC2_2400,
                    0x06: CODEC2_3200}

    def __init__(self, mode=CODEC2_2400):
        self.frame_quanta_ms = self.FRAME_QUANTA_MS
        self.channels = 1
        self.bitdepth = 16
        self.c2 = None
        self.output_samplerate = self.OUTPUT_RATE
        self.set_mode(mode)

    def set_mode(self, mode):
        self.mode = mode
        self.mode_header = self.MODE_HEADERS[self.mode].to_bytes()
        self.c2 = pycodec2.Codec2(self.mode)

    def encode(self, frame):
        if frame.shape[1] == 0:
            raise CodecError("Cannot encode frame with 0 channels")
        elif frame.shape[1] > self.channels:
            frame = frame[:, 1]

        input_samples = frame*self.TYPE_MAP_FACTOR
        input_samples = input_samples.astype(np.int16)

        if self.source:
            if self.source.samplerate != self.INPUT_RATE:
                frame_bytes = input_samples.tobytes()
                resampled_bytes = resample_bytes(frame_bytes, self.bitdepth, self.channels, self.source.samplerate, self.INPUT_RATE)
                input_samples = np.frombuffer(resampled_bytes, dtype=np.int16)
        
        SPF = self.c2.samples_per_frame()
        N_FRAMES = math.floor(len(input_samples)/SPF)
        input_frames = np.array(input_samples[0:N_FRAMES*SPF], dtype=np.int16)
        
        encoded = b""
        for pi in range(0, N_FRAMES):
            pstart = pi*SPF
            pend = (pi+1)*SPF
            input_frame = input_frames[pstart:pend]
            encoded_frame = self.c2.encode(input_frame)
            encoded += encoded_frame

        # TODO: Remove debug
        # print(f"SPF         : {SPF}")
        # print(f"N_FRAMES    : {N_FRAMES}")

        return self.mode_header+encoded

    def decode(self, frame_bytes):
        frame_header = frame_bytes[0]
        frame_bytes  = frame_bytes[1:]
        
        if frame_header in self.HEADER_MODES: frame_mode = self.HEADER_MODES[frame_header]
        else:                                 frame_mode = self.mode
        if self.mode != frame_mode:
            self.set_mode(frame_mode)

        SPF = self.c2.samples_per_frame()
        BPF = self.c2.bytes_per_frame()
        STRUCT_FORMAT = f"{SPF}h"
        N_FRAMES = math.floor(len(frame_bytes)/BPF)

        # TODO: Remove debug
        # print(f"BPF         : {BPF}")
        # print(f"N_FRAMES    : {N_FRAMES}")

        decoded = b""
        for pi in range(0, N_FRAMES):
            pstart = pi*BPF
            pend = (pi+1)*BPF
            encoded_frame = frame_bytes[pstart:pend]
            decoded_frame = self.c2.decode(encoded_frame)
            decoded += struct.pack(STRUCT_FORMAT, *decoded_frame)

        if self.sink:
            if self.sink.samplerate != self.OUTPUT_RATE:
                decoded = resample_bytes(decoded, self.bitdepth, self.channels, self.OUTPUT_RATE, self.sink.samplerate)

        decoded_samples = np.frombuffer(decoded, dtype="int16")/self.TYPE_MAP_FACTOR
        frame_samples = np.zeros((len(decoded_samples), 1), dtype="float32")
        frame_samples[:, 0] = decoded_samples

        return frame_samples