from .Sources import *
from .Sinks   import *
from .Codecs  import *
from .Mixer   import Mixer
from .Network import Packetizer

class PipelineError(Exception):
    pass

class Pipeline():
    def __init__(self, source, codec, sink, processor = None):
        if not issubclass(type(source), Source): raise PipelineError("Audio pipeline initialised with invalid source")
        if not issubclass(type(sink), Sink)    : raise PipelineError("Audio pipeline initialised with invalid sink")
        if not issubclass(type(codec), Codec)  : raise PipelineError("Audio pipeline initialised with invalid codec")
        self._codec          = None
        self.source          = source
        self.source.pipeline = self
        self.source.sink     = sink
        self.codec           = codec

        if isinstance(sink, Loopback):     sink.samplerate = source.samplerate
        if isinstance(source, Loopback):   source._sink = sink
        if isinstance(sink, Packetizer):   sink.source = source
        if isinstance(sink, OpusFileSink): sink.source = source

    @property
    def codec(self):
        if self.source:
            return self.source.codec
        else:
            return None

    @codec.setter
    def codec(self, codec):
        if not self._codec == codec:
            self._codec = codec
            self.source.codec = self._codec
            self.source.codec.sink   = self.sink
            self.source.codec.source = self.source

    @property
    def sink(self):
        if self.source:
            return self.source.sink
        else:
            return None

    @property
    def running(self):
        return self.source.should_run

    def start(self):
        if not self.running:
            self.source.start()

    def stop(self):
        if self.running:
            self.source.stop()