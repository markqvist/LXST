import RNS
import numpy as np
from .Codec import Codec

class Raw(Codec):
    BITDEPTH_16  = 0x00
    BITDEPTH_32  = 0x01
    BITDEPTH_64  = 0x02
    BITDEPTH_128 = 0x03
    BITDEPTHS = ["float16", "float32", "float64", "float128"]

    def __init__(self, channels=None, bitdepth=16):
        if channels:
            channels = min(max(channels, 1), 32)

        self.bitdepth = bitdepth
        self.channels = channels

        if self.bitdepth >= 128:
            self.dtype           = self.BITDEPTHS[self.BITDEPTH_128]
            self.header_bitdpeth = self.BITDEPTH_128
        elif self.bitdepth >= 64:
            self.dtype           = self.BITDEPTHS[self.BITDEPTH_64]
            self.header_bitdpeth = self.BITDEPTH_64
        elif self.bitdepth >= 32:
            self.dtype           = self.BITDEPTHS[self.BITDEPTH_32]
            self.header_bitdpeth = self.BITDEPTH_32
        else:
            self.dtype           = self.BITDEPTHS[self.BITDEPTH_16]
            self.header_bitdpeth = self.BITDEPTH_16

    def encode(self, frame):
        if self.channels == None:
            self.channels = frame.shape[1]
            RNS.log(f"{self} encoder set to {self.channels} channels", RNS.LOG_DEBUG)

        if frame.shape[1] > self.channels:
            frame = frame[:, range(0, self.channels)]
        elif frame.shape[1] < self.channels:
            new_frame = np.zeros(shape=(frame.shape[0], self.channels))
            for n in range(0, frame.shape[1]): new_frame[:, n] = frame[:, n]
            for n in range(frame.shape[1], new_frame.shape[1]): new_frame[:, n] = frame[:, frame.shape[1]-1]
            frame = new_frame

        frame_header = (self.header_bitdpeth << 6) | self.channels-1
        frame_bytes = frame_header.to_bytes()+frame.astype(self.dtype).tobytes()
        return frame_bytes

    def decode(self, frame_bytes):
        frame_header   = frame_bytes[0]
        frame_channels = (frame_header & 0b00111111)+1
        frame_bitdepth = frame_header >> 6
        frame_dtype    = self.BITDEPTHS[frame_bitdepth]
        frame_samples  = np.frombuffer(frame_bytes[1:], dtype=frame_dtype)
        frame_samples  = frame_samples.reshape(len(frame_samples)//frame_channels, frame_channels)
        if not self.channels: self.channels = frame_channels

        return frame_samples