#!/bin/bash
# This script is used to run the binary wheel builds
# inside docker containers for multi-arch compilation
set -e -x

yum install -y gcc gcc-c++ make codec2-devel codec2

PYTHON_VERSIONS=(
    "cp311-cp311"
    "cp312-cp312"
    "cp313-cp313"
    "cp314-cp314"
)

for PY_TAG in "${PYTHON_VERSIONS[@]}"; do
    PYBIN="/opt/python/${PY_TAG}/bin"
    
    if [ ! -d "$PYBIN" ]; then
        echo "Python version not found: $PYBIN"
        continue
    fi
    
    echo "Building with: $PYBIN"
    "${PYBIN}/pip" install cffi
    "${PYBIN}/pip" wheel /io/ -w wheelhouse/
done