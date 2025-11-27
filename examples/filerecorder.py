import sys
import time
import select
from LXST.Primitives.Recorders import FileRecorder

filename = "recording.opus"

# With default profile (maximum quality)
recorder = FileRecorder(filename)

# Or, with specific profile
# from LXST.Codecs import Opus
# recorder = FileRecorder(filename, profile=Opus.PROFILE_VOICE_MEDIUM)

recorder.start()
print("Recording started")

try: input()
except KeyboardInterrupt: pass

recorder.stop()
print(f"Recording saved to {filename}")

time.sleep(0.2)