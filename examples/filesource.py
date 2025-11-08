import LXST
import time

target_frame_ms = 40
selected_source = LXST.Sources.OpusFileSource("./docs/speech_stereo.opus", loop=True, target_frame_ms=target_frame_ms)

line_sink   = LXST.Sinks.LineSink()
loopback    = LXST.Sources.Loopback()

raw             = LXST.Codecs.Raw()
input_pipeline  = LXST.Pipeline(source=selected_source, codec=raw, sink=loopback)
output_pipeline = LXST.Pipeline(source=loopback, codec=raw, sink=line_sink)

input_pipeline.start(); output_pipeline.start()
input()
input_pipeline.stop()

time.sleep(1)