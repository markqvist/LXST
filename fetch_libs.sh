#!/bin/bash

TARGET_DIR="${1:-./lib/dev}"
mkdir -p "$TARGET_DIR"

echo "Copying native libraries to $TARGET_DIR..."
find ./build -name "filterlib*.*" -type f \( -name "*.so" -o -name "*.dll" -o -name "*.dylib" \) -exec cp {} "$TARGET_DIR/" \;

echo "Done. Copied files:"
ls -lh "$TARGET_DIR/"