from .Codec import CodecError as CodecError
from .Codec import Codec as Codec
from .Codec import Null as Null
from .Raw import Raw as Raw
from .Codec2 import Codec2 as Codec2
from .Opus import Opus as Opus

NULL   = 0xFF
RAW    = 0x00
OPUS   = 0x01
CODEC2 = 0x02

def codec_header_byte(codec):
    if codec == Raw:
        return RAW.to_bytes()
    elif codec == Opus:
        return OPUS.to_bytes()
    elif codec == Codec2:
        return CODEC2.to_bytes()

    raise TypeError(f"No header mapping for codec type {codec}")

def codec_type(header_byte):
    if header_byte == RAW:
        return Raw
    elif header_byte == OPUS:
        return Opus
    elif header_byte == CODEC2:
        return Codec2