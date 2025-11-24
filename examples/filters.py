import RNS
import LXST
import sys
import time

from LXST.Filters import BandPass, AGC

target_frame_ms  = 40
raw              = LXST.Codecs.Raw()

filters      = [BandPass(200, 8500), AGC()]

line_sink    = LXST.Sinks.LineSink()
mixer        = LXST.Mixer(target_frame_ms=target_frame_ms, sink=line_sink)
line_source  = LXST.Sources.LineSource(target_frame_ms=target_frame_ms, codec=raw, sink=mixer, filters=filters)

mixer.start()
line_source.start()
print("Hit enter stop"); input()

line_source.stop()

time.sleep(0.5)