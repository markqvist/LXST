import RNS
from .Pipeline import Pipeline
from .Codecs import *
from .Sources import *
from .Sinks import *
from . import APP_NAME

class CallEndpoint():
    def __init__(self, identity):
        self.identity = identity
        self.destination = RNS.Destination(self.identity, RNS.Destination.IN, RNS.Destination.SINGLE, APP_NAME, "call", "endpoint")
        self.destination.set_link_established_callback(self._incoming_call)
        self.active_call = None
        self.auto_answer = True
        self.receive_pipeline = None
        self.transmit_pipeline = None
        self._incoming_call_callback = None

    def announce(self):
        if self.destination:
            self.destination.announce()

    @property
    def incoming_call_callback(self):
        return self._incoming_call_callback

    @incoming_call_callback.setter
    def incoming_call_callback(self, callback):
        if callable(callback):
            self._incoming_call_callback = callback
        else:
            raise TypeError(f"Invalid callback for {self}: Not callable")

    def _incoming_call(self, link):
        RNS.log(f"Incoming call on {self}", RNS.LOG_DEBUG)
        if callable(self._incoming_call_callback):
            self._incoming_call_callback(link)

    def answer(self, call_link):
        RNS.log(f"Answering call on {call_link}", RNS.LOG_DEBUG)
        self.active_call = call_link

        self.receive_pipeline  = Pipeline(source=PacketSource(self),
                                          codec=Opus(),
                                          sink=LineSink())
        
        self.transmit_pipeline = Pipeline(source=LineSource(target_frame_ms=target_frame_ms),
                                          codec=Opus(),
                                          sink=PacketSink(self))

    def terminate(self):
        self.receive_pipeline.stop()
        self.transmit_pipeline.stop()
        if self.active_call:
            self.active_call.teardown()