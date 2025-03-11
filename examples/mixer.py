import RNS
import LXST
import sys
import time
RNS.loglevel = RNS.LOG_DEBUG

target_frame_ms  = 20
pipelined_output = True
raw              = LXST.Codecs.Raw()

# Pipelined mixer example
if pipelined_output:
    opus         = LXST.Codecs.Opus(profile=LXST.Codecs.Opus.PROFILE_AUDIO_HIGH)
    codec2       = LXST.Codecs.Codec2(mode=LXST.Codecs.Codec2.CODEC2_3200)
    line_sink    = LXST.Sinks.LineSink()
    mixer        = LXST.Mixer(target_frame_ms=target_frame_ms)
    loopback     = LXST.Sources.Loopback()

    codec        = opus
    
    file_source1 = LXST.Sources.OpusFileSource("./docs/speech_stereo.opus", codec=raw, sink=mixer, loop=True, target_frame_ms=target_frame_ms)
    file_source2 = LXST.Sources.OpusFileSource("./docs/podcast.opus", codec=raw, sink=mixer, loop=True, target_frame_ms=target_frame_ms)
    line_source  = LXST.Sources.LineSource(target_frame_ms=target_frame_ms, codec=raw, sink=mixer)

    input_pipeline  = LXST.Pipeline(source=mixer, codec=codec, sink=loopback)
    output_pipeline = LXST.Pipeline(source=loopback, codec=codec, sink=line_sink)
    input_pipeline.start(); output_pipeline.start()

# Simple mixer example with output directly to sink
else:
    line_sink    = LXST.Sinks.LineSink()
    mixer        = LXST.Mixer(target_frame_ms=target_frame_ms, sink=line_sink)
    file_source1 = LXST.Sources.OpusFileSource("./docs/speech_stereo.opus", codec=raw, sink=mixer, loop=True, target_frame_ms=target_frame_ms)
    file_source2 = LXST.Sources.OpusFileSource("./docs/podcast.opus", codec=raw, sink=mixer, loop=True, target_frame_ms=target_frame_ms)
    line_source  = LXST.Sources.LineSource(target_frame_ms=target_frame_ms, codec=raw, sink=mixer)

mixer.start()
line_source.start()
print("Hit enter to add another source"); input()

file_source1.start()
print("Hit enter to add another source"); input()

file_source2.start()
print("Hit enter to stop all sources"); input()

file_source1.stop()
file_source2.stop()
line_source.stop()

time.sleep(0.5)