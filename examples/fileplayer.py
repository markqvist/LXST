import sys
import time
import select
from LXST.Primitives.Players import FilePlayer

loop = False

if loop:
    player = FilePlayer("./docs/speech_stereo.opus", loop=True)
    player.start()

    while player.running:
        i, o, e = select.select([sys.stdin], [], [], 1.0)
        if (i): player.stop()

else:
    player = FilePlayer("./docs/speech_stereo.opus")
    player.start()

    while player.running: time.sleep(0.1)

print("Playback finished")