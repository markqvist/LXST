#!/bin/bash

docker run --rm -v $(pwd):/io quay.io/pypa/manylinux_2_34_x86_64 /io/build_wheels.sh
docker run --rm -v $(pwd):/io quay.io/pypa/manylinux_2_34_aarch64 /io/build_wheels.sh
docker run --rm -v $(pwd):/io quay.io/pypa/manylinux_2_39_riscv64 /io/build_wheels.sh

# docker run --rm -v $(pwd):/io quay.io/pypa/manylinux_2_31_armv7l /io/build_wheels.sh
# docker run --rm -v $(pwd):/io quay.io/pypa/musllinux_1_2_x86_64 /io/build_wheels.sh
# docker run --rm -v $(pwd):/io quay.io/pypa/musllinux_1_2_aarch64 /io/build_wheels.sh
# docker run --rm -v $(pwd):/io quay.io/pypa/musllinux_1_2_armv7l /io/build_wheels.sh
# docker run --rm -v $(pwd):/io quay.io/pypa/musllinux_1_2_riscv64 /io/build_wheels.sh

./fetch_libs.sh