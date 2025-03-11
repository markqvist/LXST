import io
import RNS
import time
import math
import numpy as np
from .Codec import Codec, CodecError, resample_bytes
from .libs.pyogg import OpusEncoder, OpusDecoder

class Opus(Codec):
    FRAME_QUANTA_MS = 2.5
    FRAME_MAX_MS    = 60
    VALID_FRAME_MS  = [2.5, 5, 10, 20, 40, 60]
    TYPE_MAP_FACTOR = np.iinfo("int16").max

    PROFILE_VOICE_LOW    = 0x00
    PROFILE_VOICE_MEDIUM = 0x01
    PROFILE_VOICE_HIGH   = 0x02
    PROFILE_VOICE_MAX    = 0x03
    PROFILE_AUDIO_MIN    = 0x04
    PROFILE_AUDIO_LOW    = 0x05
    PROFILE_AUDIO_MEDIUM = 0x06
    PROFILE_AUDIO_HIGH   = 0x07
    PROFILE_AUDIO_MAX    = 0x08

    def __init__(self, profile=PROFILE_VOICE_LOW):
        self.frame_quanta_ms = self.FRAME_QUANTA_MS
        self.frame_max_ms    = self.FRAME_MAX_MS
        self.valid_frame_ms  = self.VALID_FRAME_MS
        self.channels = 1
        self.input_channels = 1
        self.output_channels = 2
        self.bitdepth = 16
        self.opus_encoder = OpusEncoder()
        self.opus_decoder = OpusDecoder()
        self.encoder_configured = False
        self.decoder_configured = False
        self.bitrate_ceiling = 6000
        self.output_bytes = 0
        self.output_ms = 0
        self.output_bitrate = 0
        self.set_profile(profile)

    def set_profile(self, profile):
        if profile == self.PROFILE_VOICE_LOW:
            self.profile = profile
            self.channels = 1
            self.input_channels = self.channels
            self.output_samplerate = 8000
            self.opus_encoder.set_application("voip")
        elif profile == self.PROFILE_VOICE_MEDIUM:
            self.profile = profile
            self.channels = 1
            self.input_channels = self.channels
            self.output_samplerate = 24000
            self.opus_encoder.set_application("voip")
        elif profile == self.PROFILE_VOICE_HIGH:
            self.profile = profile
            self.channels = 1
            self.input_channels = self.channels
            self.output_samplerate = 48000
            self.opus_encoder.set_application("voip")
        elif profile == self.PROFILE_VOICE_MAX:
            self.profile = profile
            self.channels = 2
            self.input_channels = self.channels
            self.output_samplerate = 48000
            self.opus_encoder.set_application("voip")
        elif profile == self.PROFILE_AUDIO_MIN:
            self.profile = profile
            self.channels = 1
            self.input_channels = self.channels
            self.output_samplerate = 8000
            self.opus_encoder.set_application("audio")
        elif profile == self.PROFILE_AUDIO_LOW:
            self.profile = profile
            self.channels = 1
            self.input_channels = self.channels
            self.output_samplerate = 12000
            self.opus_encoder.set_application("audio")
        elif profile == self.PROFILE_AUDIO_MEDIUM:
            self.profile = profile
            self.channels = 2
            self.input_channels = self.channels
            self.output_samplerate = 24000
            self.opus_encoder.set_application("audio")
        elif profile == self.PROFILE_AUDIO_HIGH:
            self.profile = profile
            self.channels = 2
            self.input_channels = self.channels
            self.output_samplerate = 48000
            self.opus_encoder.set_application("audio")
        elif profile == self.PROFILE_AUDIO_MAX:
            self.profile = profile
            self.channels = 2
            self.input_channels = self.channels
            self.output_samplerate = 48000
            self.opus_encoder.set_application("audio")
        else:
            raise CodecError(f"Unsupported profile configured for {self}")

    def update_bitrate(self, frame_duration_ms):
        if self.profile == self.PROFILE_VOICE_LOW:
            self.bitrate_ceiling = 6000
        elif self.profile == self.PROFILE_VOICE_MEDIUM:
            self.bitrate_ceiling = 8000
        elif self.profile == self.PROFILE_VOICE_HIGH:
            self.bitrate_ceiling = 16000
        elif self.profile == self.PROFILE_VOICE_MAX:
            self.bitrate_ceiling = 32000
        elif self.profile == self.PROFILE_AUDIO_MIN:
            self.bitrate_ceiling = 8000
        elif self.profile == self.PROFILE_AUDIO_LOW:
            self.bitrate_ceiling = 14000
        elif self.profile == self.PROFILE_AUDIO_MEDIUM:
            self.bitrate_ceiling = 28000
        elif self.profile == self.PROFILE_AUDIO_HIGH:
            self.bitrate_ceiling = 56000
        elif self.profile == self.PROFILE_AUDIO_MAX:
            self.bitrate_ceiling = 128000

        max_bytes_per_frame = math.ceil((self.bitrate_ceiling/8)*(frame_duration_ms/1000))
        configured_bitrate = (max_bytes_per_frame*8)/(frame_duration_ms/1000)
        self.opus_encoder.set_max_bytes_per_frame(max_bytes_per_frame)

    def encode(self, frame):
        if frame.shape[1] == 0:
            raise CodecError("Cannot encode frame with 0 channels")
        elif frame.shape[1] > self.input_channels:
            frame = frame[:, 0:self.input_channels]
        elif frame.shape[1] < self.input_channels:
            new_frame = np.zeros(shape=(frame.shape[0], self.input_channels))
            for n in range(0, frame.shape[1]): new_frame[:, n] = frame[:, n]
            for n in range(frame.shape[1], new_frame.shape[1]): new_frame[:, n] = frame[:, frame.shape[1]-1]
            frame = new_frame

        input_samples = frame*self.TYPE_MAP_FACTOR
        input_samples = input_samples.astype(np.int16)

        if self.source.samplerate != self.output_samplerate:
            frame_bytes = input_samples.tobytes()
            resampled_bytes = resample_bytes(frame_bytes, self.bitdepth, self.input_channels, self.source.samplerate, self.output_samplerate)
            input_samples = np.frombuffer(resampled_bytes, dtype=np.int16)
            input_samples = input_samples.reshape(len(input_samples)//self.input_channels, self.input_channels)

        frame_duration_ms = (input_samples.shape[0]/self.output_samplerate)*1000
        self.update_bitrate(frame_duration_ms)

        if not self.encoder_configured:
            self.input_channels = self.channels
            self.opus_encoder.set_sampling_frequency(self.output_samplerate)
            self.opus_encoder.set_channels(self.input_channels)
            RNS.log(f"{self} encoder set to {self.input_channels} channels, {RNS.prettyfrequency(self.output_samplerate)}", RNS.LOG_DEBUG)
            self.encoder_configured = True

        input_bytes = input_samples.tobytes()
        # TODO: Pad input bytes on partial frame
        encoded_frame = self.opus_encoder.encode(input_bytes).tobytes()

        self.output_bytes += len(encoded_frame)
        self.output_ms += frame_duration_ms
        self.output_bitrate = (self.output_bytes*8)/(self.output_ms/1000)

        return encoded_frame

    def decode(self, frame_bytes):
        if not self.decoder_configured:
            if self.sink and self.sink.channels: output_channels = self.sink.channels
            else: output_channels = self.output_channels if self.output_channels > self.channels else self.channels
            self.channels = output_channels
            self.opus_decoder.set_channels(output_channels)
            self.opus_decoder.set_sampling_frequency(self.sink.samplerate)
            self.decoder_configured = True
            RNS.log(f"{self} decoder set to {self.channels} channels, {RNS.prettyfrequency(self.sink.samplerate)}", RNS.LOG_DEBUG)

        decoded_frame_bytes = self.opus_decoder.decode(memoryview(bytearray(frame_bytes)))
        decoded_samples = np.frombuffer(decoded_frame_bytes, dtype="int16")/self.TYPE_MAP_FACTOR
        frame_samples = decoded_samples.reshape(len(decoded_samples)//self.channels, self.channels)

        return frame_samples