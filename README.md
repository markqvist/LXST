# Lightweight Extensible Signal Transport

LXST is a simple and flexible real-time streaming format and delivery protocol that allows a wide variety of implementations, while using as little bandwidth as possible. It is built on top of [Reticulum](https://reticulum.network) and offers zero-conf stream routing, end-to-end encryption and Forward Secrecy, and can be transported over any kind of medium that Reticulum supports.

- Provides a variety of ready-to-use primitives, for easily creating applications such as:
  - Telephony and live voice calls
  - Two-way radio systems
    - Direct peer-to-peer radio communications
    - Trunked and routed real-time radio systems
  - Media streaming
  - Broadcast radio
  - Public address systems
- Can handle real-time signal streams with end-to-end latencies below 10 milliseconds
- Supports encoding and decoding stream contents with a range of different codecs
  - Raw and lossless streams with arbitrary sample rates
    - Up to 32 channels
    - Up to 128-bit sample precision
  - Efficient, high-quality voice and audio with OPUS
    - Many different built-in profiles, from ~4.5kbps to ~96kbps
    - Profiles are pre-tuned for different applications, such as:
      - Low-bandwidth voice
      - Medium quality voice
      - High quality, perceptually lossless voice
      - Media content such as podcasts
      - Perceptually lossless stereo music
  - Ultra low-bandwidth voice communications with Codec2
    - Provides intelligible voice between 700bps and 3200bps
- Can dynamically switch codecs mid-stream without stream re-initialization or frame loss
- Has in-band signalling support for call signalling, communications, metadata embedding, media and stream management
- Uses a fully staged signal pipelining, allowing arbitrary stream routing
- Provides built-in signal mixing support for any number of channels

## Transport Encryption

LXST uses encryption provided by [Reticulum](https://reticulum.network), and thus provides end-to-end encryption, guaranteed data integrity and authenticity, as well as forward secrecy by default.

## Project Status & License

This software is in a very early alpha state, and will change rapidly with ongoing development. Consider no APIs stable. Consider everything explosive. Not all features are implemented. Nothing is documented. For a fully functional LXST program, take a look at the included `rnphone` program, which provides telephony service over Reticulum. Everything else will currently be a voyage of your own making.

While under early development, the project is kept under a `CC BY-NC-ND 4.0` license.

## Installation

If you want to try out LXST, you can install it with pip:

```bash
pip install lxst
```

On Raspberry Pi, install various dependencies with:

```bash
# Audio codecs
sudo apt install python3-pip python3-pyaudio python3-dev python3-cryptography build-essential libopusfile0 libsdl2-dev libavcodec-dev libavdevice-dev libavfilter-dev portaudio19-dev codec2 libcodec2-1.0 xclip xsel
wget https://raw.githubusercontent.com/markqvist/Sideband/main/docs/utilities/pycodec2-3.0.1-cp311-cp311-linux_aarch64.whl
pip install ./pycodec2-3.0.1-cp311-cp311-linux_aarch64.whl --break-system-packages

# For hardware control over I2C:
pip install smbus2 --break-system-packages # Install smbus module if not already installed
sudo raspi-config # Enable the I2C bus under "Interface Options"
sudo apt install python3-rpi.gpio # Install gpio module system-wide
```