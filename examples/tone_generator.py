import RNS
import LXST
import sys
import time
RNS.loglevel = RNS.LOG_DEBUG

target_frame_ms = 40
tone            = LXST.Generators.ToneSource(frequency=388, ease_time_ms=3.14159, target_frame_ms=target_frame_ms)
line_sink       = LXST.Sinks.LineSink()
output_pipeline = LXST.Pipeline(source=tone, codec=LXST.Codecs.Null(), sink=line_sink)

output_pipeline.start(); input()
tone.stop()

time.sleep(1)