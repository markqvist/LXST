import RNS
import LXST
import sys
import time
RNS.loglevel = RNS.LOG_DEBUG

if len(sys.argv) < 2:
    print("No codec specified")
    sys.exit(0)
else:
    selected_codec = sys.argv[1]

if len(sys.argv) >= 4:
    target_frame_ms = int(sys.argv[3])
else:
    target_frame_ms = 40

if len(sys.argv) >= 3 and sys.argv[2].lower() == "file":
    selected_source = LXST.Sources.OpusFileSource("./docs/speech_stereo.opus", loop=True, target_frame_ms=target_frame_ms)
    # selected_source = LXST.Sources.OpusFileSource("./docs/music_stereo.opus", loop=True, target_frame_ms=target_frame_ms)
    # selected_source = LXST.Sources.OpusFileSource("./docs/podcast.opus", loop=True, target_frame_ms=target_frame_ms)
else:
    selected_source = LXST.Sources.LineSource(target_frame_ms=target_frame_ms)

line_sink   = LXST.Sinks.LineSink()
loopback    = LXST.Sources.Loopback()

if selected_codec.lower() == "raw":
    raw             = LXST.Codecs.Raw()
    input_pipeline  = LXST.Pipeline(source=selected_source, codec=raw, sink=loopback)
    output_pipeline = LXST.Pipeline(source=loopback, codec=raw, sink=line_sink)
elif selected_codec.lower() == "codec2":
    codec2          = LXST.Codecs.Codec2(mode=LXST.Codecs.Codec2.CODEC2_1600)
    input_pipeline  = LXST.Pipeline(source=selected_source, codec=codec2, sink=loopback)
    output_pipeline = LXST.Pipeline(source=loopback, codec=codec2, sink=line_sink)
elif selected_codec.lower() == "opus":
    opus            = LXST.Codecs.Opus(profile=LXST.Codecs.Opus.PROFILE_VOICE_LOW)
    input_pipeline  = LXST.Pipeline(source=selected_source, codec=opus, sink=loopback)
    output_pipeline = LXST.Pipeline(source=loopback, codec=opus, sink=line_sink)
else:
    print("No valid codec selected")
    sys.exit(0)

input_pipeline.start(); output_pipeline.start()
input()
input_pipeline.stop()

time.sleep(1)