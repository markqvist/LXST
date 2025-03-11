import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

exec(open("LXST/_version.py", "r").read())

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
    install_requires=["rns>=0.9.2",
                      "soundcard",
                      "numpy",
                      "pycodec2",
                      "audioop-lts>=0.2.1;python_version>='3.13'"],
    python_requires=">=3.7",
)