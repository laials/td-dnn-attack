#!/bin/bash
# Build script for the GPA helper shared library.
# Run inside the TD guest in the dnn-victim directory.
set -e
echo "Building libgpa_helper.so..."
gcc -O2 -shared -fPIC -o libgpa_helper.so gpa_helper.c
echo "Done. libgpa_helper.so is ready."