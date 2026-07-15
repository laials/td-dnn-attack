"""
victim_numpy_mlp.py

NumPy MLP victim for the TDXRay DNN side-channel attack.
Runs a 3-layer fully connected network inside the TD guest.
Marker pages are touched at layer boundaries so the host-side
page-fault attack can synchronize with each layer's execution.

Markers:
    INF_START / TERM    - inference boundaries
    L1_START / L1_END   - layer 1 (W1: large FC, high L3 pressure)
    L2_START / L2_END   - layer 2 (W2: medium FC)
    L3_START / L3_END   - layer 3 (W3: small FC, fits in L2)

Weight matrix sizes (float32):
    W1: 406 x 2048  (~3.2 MB)  -> causes heavy L3 eviction
    W2: 2048 x 1024 (~8 MB)    -> moderate eviction
    W3: 1024 x 128  (~0.5 MB)  -> fits comfortably in L3
"""

import time
import ctypes
import numpy as np

np.random.seed(42)

# ---------------------------------------------------------------------------
# GPA helper - translates virtual addresses to guest physical addresses
# ---------------------------------------------------------------------------
gpa = ctypes.CDLL("./libgpa_helper.so")
gpa.virt_to_phys.argtypes = [ctypes.c_void_p]
gpa.virt_to_phys.restype  = ctypes.c_ulong

def print_gpa(name, arr):
    addr = arr.ctypes.data
    phys = gpa.virt_to_phys(ctypes.c_void_p(addr))
    print(f"{name} GPA: 0x{phys:x}", flush=True)

# ---------------------------------------------------------------------------
# Marker page mechanism
# Each marker is an 8MB allocation with the touch point at the 4MB offset,
# keeping it on a distinct physical page away from other allocations.
# ---------------------------------------------------------------------------
_marker_keepalive = []

def make_marker():
    marker = np.zeros(8 * 1024 * 1024, dtype=np.uint8)
    offset = 4 * 1024 * 1024
    marker[offset] = 1
    _marker_keepalive.append(marker)
    return marker[offset:]

def touch_marker(marker):
    marker[0] ^= 1

# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------
def relu(x):
    return np.maximum(x, 0)

# ---------------------------------------------------------------------------
# Model weights  (fixed seed for reproducibility)
# ---------------------------------------------------------------------------
W1 = np.random.randn(406,  2048).astype(np.float32)
b1 = np.random.randn(2048).astype(np.float32)

W2 = np.random.randn(2048, 1024).astype(np.float32)
b2 = np.random.randn(1024).astype(np.float32)

W3 = np.random.randn(1024,  128).astype(np.float32)
b3 = np.random.randn(128).astype(np.float32)

# Input
X  = np.random.randn(1, 406).astype(np.float32)

# ---------------------------------------------------------------------------
# Marker pages
# ---------------------------------------------------------------------------
inf_start  = make_marker()
l1_start   = make_marker()
l1_end     = make_marker()
l2_start   = make_marker()
l2_end     = make_marker()
l3_start   = make_marker()
l3_end     = make_marker()
termination = make_marker()

# ---------------------------------------------------------------------------
# Print GPAs so the host attack binary knows which pages to block
# ---------------------------------------------------------------------------
print("MODEL: NUMPY_MLP", flush=True)
print_gpa("Inference start marker", inf_start)
print_gpa("Layer 1 start marker",   l1_start)
print_gpa("Layer 1 end marker",     l1_end)
print_gpa("Layer 2 start marker",   l2_start)
print_gpa("Layer 2 end marker",     l2_end)
print_gpa("Layer 3 start marker",   l3_start)
print_gpa("Layer 3 end marker",     l3_end)
print_gpa("Termination marker",     termination)

# ---------------------------------------------------------------------------
# Inference loop
# ---------------------------------------------------------------------------
i = 0
while True:
    print(f"INFERENCE {i} START", flush=True)
    touch_marker(inf_start)

    # Layer 1 - large weight matrix, heavy L3 pressure
    touch_marker(l1_start)
    h1 = relu(X @ W1 + b1)
    touch_marker(l1_end)

    # Layer 2 - medium weight matrix
    touch_marker(l2_start)
    h2 = relu(h1 @ W2 + b2)
    touch_marker(l2_end)

    # Layer 3 - small weight matrix, fits in L3
    touch_marker(l3_start)
    h3 = h2 @ W3 + b3
    touch_marker(l3_end)

    print(f"INFERENCE {i} END", flush=True)
    touch_marker(termination)

    time.sleep(0.5)
    i += 1