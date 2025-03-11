import numpy as np
from .libs.pydub import AudioSegment

TYPE_MAP_FACTOR = np.iinfo("int16").max

class Codec():
    preferred_samplerate = None
    frame_quanta_ms      = None
    frame_max_ms         = None
    valid_frame_ms       = None
    source               = None
    sink                 = None

class CodecError(Exception):
    pass

class Null(Codec):
    def __init__(self):
        pass

    def encode(self, frame):
        return frame

    def decode(self, frame):
        return frame

def resample_bytes(sample_bytes, bitdepth, channels, input_rate, output_rate, normalize=False):
    sample_width = bitdepth//8
    audio = AudioSegment(
        sample_bytes,
        frame_rate=input_rate,
        sample_width=sample_width,
        channels=channels)

    if normalize:
        audio = audio.apply_gain(-audio.max_dBFS)

    resampled_audio = audio.set_frame_rate(output_rate)
    resampled_bytes = resampled_audio.get_array_of_samples().tobytes()

    # rate_factor = input_rate/output_rate
    # input_samples = int(len(sample_bytes)/channels/sample_width)
    # output_samples = int(len(resampled_bytes)/channels/sample_width)
    # target_samples = int(input_samples/rate_factor)
    # if output_samples < target_samples:
    #     print("Mismatch")
    #     add_samples = int(target_samples-output_samples)
    #     fill = resampled_bytes[-sample_width:]*add_samples
    #     resampled_bytes += fill

    return resampled_bytes

def resample(input_samples, bitdepth, channels, input_rate, output_rate, normalize=False):
    sample_width = bitdepth//8
    input_samples = input_samples*TYPE_MAP_FACTOR
    input_samples = input_samples.astype(np.int16)    
    resampled_bytes = resample_bytes(input_samples.tobytes(), bitdepth, channels, input_rate, output_rate, normalize)
    output_samples = np.frombuffer(resampled_bytes, dtype=np.int16)/TYPE_MAP_FACTOR
    output_samples = output_samples.reshape(output_samples.shape[0]//channels, channels)
    output_samples = output_samples.astype(np.float32)

    return output_samples