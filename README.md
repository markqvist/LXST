# Lightweight Extensible Signal Transport

> [!WARNING]
> Several hastily launched, incorrect, and in most cases entirely LLM-generated fakes of LXST and associated tools and applications are currently being circulated and marketed. Most of these "projects" violate the license that LXST was published under, but claim independent ownership and license grants. Such claims or grants are **not** legally valid, and **not** recognized by the LXST author and copyright holder.
>
> Any claimed assertion of copyright or grant of license that such projects are making are [void grants](https://reticulum.network/manual/brandolinis.html#void-grants-legal-foundations-of-machine-generated-code).
>
> Both the violators themselves, and **all** downstream projects using the infringing derivatives, are **directly** and **personally** liable for the legal consequences.
>
> For more detailed information, see the relevant sections of the [Brandolini's Reference](https://reticulum.network/manual/brandolinis.html) chapter of the Reticulum Manual. For software and projects recognized by the Reticulum community, see the [Programs Using Reticulum](https://reticulum.network/manual/software.html) chapter.
>
> Do **not** use these "projects", they are a hazard to the entire ecosystem we have been carefully building over the last ten years.

*Due to the blatant copyright infringement and LLM-laundering, the source code in this repository is no longer updated. All development is happening over Reticulum, where the latest source is available. Packages and updates continue to ship on PyPI and over `rngit`.*

LXST is a simple and flexible real-time streaming format and delivery protocol that allows a wide variety of implementations, while using as little bandwidth as possible. It is built on top of [Reticulum](https://reticulum.network) and offers zero-conf stream routing, end-to-end encryption and Forward Secrecy, and can be transported over any kind of medium that Reticulum supports.

- Cross-platform, works on Linux, Android, Windows and Mac
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

User-facing clients built on LXST include:

- [Sideband](https://unsigned.io/sideband)
- [MeshChatX](https://meshchatx.com/)
- [Partyline](https://github.com/RFnexus/partyline)
- [Columba](https://github.com/torlando-tech/columba)
- [rnphone](https://reticulum.network/manual/software.html#reticulum-network-telephone)
- [LXST Phone](https://github.com/kc1awv/lxst_phone)

## Transport Encryption

LXST uses encryption provided by [Reticulum](https://reticulum.network), and thus provides end-to-end encryption, guaranteed data integrity and authenticity, as well as forward secrecy by default.

## Project Status & License

This software and its interfaces will change rapidly with ongoing development. Consider no APIs stable. Consider everything explosive. Not all features are implemented. Nothing is documented. For a fully functional LXST program, take a look at [Sideband](https://github.com/markqvist/Sideband) or the included `rnphone` program, which provides telephony service over Reticulum. Everything else will currently be a voyage of your own making.

The LXST project is available under a `CC BY-NC-ND 4.0` license. You can deploy LXST freely for non-commercial, personal and humanitarian purposes. For commercial (including institutionalised educational) licensing, contact me.

## Installation

If you want to try out LXST, you can install it with pip:

```bash
pip install lxst
```

On Raspberry Pi (assuming Trixie / Debian 13), install various dependencies with:

```bash
# Audio codecs
sudo apt install python3-pyaudio codec2

# For hardware control over I2C:
pip install smbus2 --break-system-packages # Install smbus module if not already installed
sudo raspi-config # Enable the I2C bus under "Interface Options"
sudo apt install python3-rpi.gpio # Install gpio module system-wide
```
