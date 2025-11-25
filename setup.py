import setuptools
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
import os
import platform

if os.path.isfile("./skip_extensions"): BUILD_EXTENSIONS = False
else:                                   BUILD_EXTENSIONS = True
if os.name == "nt":                     BUILD_EXTENSIONS = False

if BUILD_EXTENSIONS: print(f"Building LXST with native extensions...")
else: print(f"Building LXST without native extensions...")

with open("README.md", "r") as fh: long_description = fh.read()
exec(open("LXST/_version.py", "r").read())

c_sources = ["LXST/Filters.c"]

if BUILD_EXTENSIONS: extensions = [ Extension("LXST.filterlib", sources=c_sources, include_dirs=["LXST"], language="c"), ]
else:                extensions = []

packages = setuptools.find_packages(exclude=[])
packages.append("LXST.Utilities")
packages.append("LXST.Primitives.hardware")
packages.append("LXST.Codecs.libs.pydub")
packages.append("LXST.Codecs.libs.pyogg")

package_data = {
"": [
    "Codecs/libs/pyogg/libs/win_amd64/*",
    "Codecs/libs/pyogg/libs/macos/*",
    "Sounds/*",
    ],
"LXST": [
    "Filters.h",
    "Filters.c",
    "filterlib*.so",
    "filterlib*.dll",
    "Platforms/linux/pulseaudio.h",
    "Platforms/darwin/coreaudio.h",
    "Platforms/windows/mediafoundation.h",
    ]
}

setuptools.setup(
    name="lxst",
    version=__version__,
    author="Mark Qvist",
    author_email="mark@unsigned.io",
    description="Lightweight Extensible Signal Transport for Reticulum",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://git.unsigned.io/markqvist/lxst",
    packages=packages,
    package_data=package_data,
    ext_modules=extensions,
    cmdclass={"build_ext": build_ext},
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: Other/Proprietary License",
        "Operating System :: OS Independent",
    ],
    entry_points= {
        'console_scripts': [
            'rnphone=LXST.Utilities.rnphone:main',
        ]
    },
    install_requires=["rns>=1.0.4",
                      "lxmf>=0.9.3",
                      "numpy>=2.3.4",
                      "pycodec2>=4.1.0",
                      "audioop-lts>=0.2.1;python_version>='3.13'",
                      "cffi>=2.0.0"],
    python_requires=">=3.11",
)
