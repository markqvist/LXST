import RNS
import time
import threading
from .Sinks import RemoteSink
from .Sources import RemoteSource
from .Codecs import Null, codec_header_byte, codec_type
from collections import deque
from RNS.vendor import umsgpack as mp

FIELD_SIGNALLING = 0x00
FIELD_FRAMES     = 0x01

class SignallingReceiver():
    def __init__(self, proxy=None):
        # TODO: Add inband signalling scheduler
        self.outgoing_signals = deque()
        self.proxy = proxy

    def handle_signalling_from(self, source):
        source.set_packet_callback(self._packet)

    def signalling_received(self, signals, source):
        if self.proxy: self.proxy.signalling_received(signals, source)

    def signal(self, signal, destination, immediate=True):
        signalling_data = {FIELD_SIGNALLING:[signal]}

        if immediate:
            signalling_packet = RNS.Packet(destination, mp.packb(signalling_data), create_receipt=False)
            signalling_packet.send()
        else:
            # TODO: Add inband signalling scheduler
            pass

    def _packet(self, data, packet, unpacked=None):
        try:
            if not unpacked: unpacked = mp.unpackb(data)
            source = packet.link if hasattr(packet, "link") else None
            if type(unpacked) == dict:
                if FIELD_SIGNALLING in unpacked:
                    signalling = unpacked[FIELD_SIGNALLING]
                    if type(signalling) == list: self.signalling_received(signalling, source)
                    else:                        self.signalling_received([signalling], source)

        except Exception as e:
            RNS.log(f"{self} could not process incoming packet: {e}", RNS.LOG_ERROR)
            RNS.trace_exception(e)

class Packetizer(RemoteSink):
    def __init__(self, destination, failure_callback=None):
        self.destination = destination
        self.should_run = False
        self.source = None
        self.transmit_failure = False
        self.__failure_calback = failure_callback

    def handle_frame(self, frame, source=None):
        if type(self.destination) == RNS.Link and not self.destination.status == RNS.Link.ACTIVE:
            return

        # TODO: Add inband signalling scheduler
        frame = codec_header_byte(type(self.source.codec))+frame
        packet_data = {FIELD_FRAMES:frame}
        frame_packet = RNS.Packet(self.destination, mp.packb(packet_data), create_receipt=False)
        if frame_packet.send() == False:
            self.transmit_failure = True
            if callable(self.__failure_calback): self.__failure_calback()

        # TODO: Remove testing
        # if not hasattr(self, "frames"):
        #     self.frames = 0
        #     self.frame_bytes = 0
        #     self.total_bytes = 0
        #     self.total_bytes = 0
        #     self.overhead_bytes = 0
        # self.frames += 1
        # self.frame_bytes += len(frame)
        # self.total_bytes += len(frame_packet.raw)
        # self.overhead_bytes += len(frame_packet.raw)-len(frame)
        # self.overhead_ratio = self.frame_bytes / self.total_bytes
        # if not hasattr(self, "started"):
        #     self.started = time.time()
        #     rate = 0
        #     codec_rate = 0
        # else:
        #     rate = (self.total_bytes*8)/(time.time()-self.started)
        #     codec_rate = (self.frame_bytes*8)/(time.time()-self.started)
        # print(f"\rP={len(frame_packet.raw)}/{len(frame)}/{len(frame_packet.raw)-len(frame)}  N={self.frames}  E={round(self.overhead_ratio*100,0)}%  O={RNS.prettysize(self.total_bytes)}  F={RNS.prettysize(self.frame_bytes)}  S={RNS.prettyspeed(rate)}  C={RNS.prettyspeed(codec_rate)}", end="            ")

    def start(self):
        if not self.should_run:
            RNS.log(f"{self} starting", RNS.LOG_DEBUG)
            self.should_run = True

    def stop(self):
        self.should_run = False

class LinkSource(RemoteSource, SignallingReceiver):
    def __init__(self, link, signalling_receiver, sink=None):
        self.should_run   = False
        self.link         = link
        self.sink         = sink
        self.codec        = Null()
        self.pipeline     = None
        self.proxy        = signalling_receiver
        self.receive_lock = threading.Lock()
        self.link.set_packet_callback(self._packet)

    def _packet(self, data, packet):
        with self.receive_lock:
            try:
                unpacked = mp.unpackb(data)
                if type(unpacked) == dict:
                    if FIELD_FRAMES in unpacked:
                        frames = unpacked[FIELD_FRAMES]
                        if type(frames) != list: frames = [frames]
                        for frame in frames:
                            frame_codec = codec_type(frame[0])
                            if self.codec and self.sink:
                                if type(self.codec) != frame_codec:
                                    RNS.log(f"Remote switched codec to {frame_codec}", RNS.LOG_DEBUG)
                                    if self.pipeline: self.pipeline.codec = frame_codec()
                                    else: self.codec = frame_codec(); self.codec.sink = self.sink
                                    decoded_frame = self.codec.decode(frame[1:])
                                    if self.codec.channels: self.channels = self.codec.channels
                                else:
                                    decoded_frame = self.codec.decode(frame[1:])

                                if self.pipeline: self.sink.handle_frame(decoded_frame, self)
                                else:             self.sink.handle_frame(decoded_frame, self, decoded=True)

                    if FIELD_SIGNALLING in unpacked:
                        super()._packet(data=None, packet=packet, unpacked=unpacked)

            except Exception as e:
                RNS.log(f"{self} could not process incoming packet: {e}", RNS.LOG_ERROR)
                RNS.trace_exception(e)

    def start(self):
        if not self.should_run:
            RNS.log(f"{self} starting", RNS.LOG_DEBUG)
            self.should_run = True

    def stop(self):
        self.should_run = False