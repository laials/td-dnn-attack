"""
victim_numpy_resnet.py

NumPy Tiny ResNet victim for the TDXRay DNN side-channel attack.
Implements a minimal residual network with two residual blocks
followed by a classifier layer, all in pure NumPy.

Markers:
    INF_START / TERM            - inference boundaries
    BLOCK1_START / BLOCK1_END   - first residual block
    BLOCK2_START / BLOCK2_END   - second residual block
    CLASSIFIER_START / END      - final FC classifier

Architecture (all float32):
    Input:      (1, 64, 64)  single-channel image
    Block 1:    32 filters, 3x3 conv, stride 1  -> (32, 62, 62)
    Block 2:    64 filters, 3x3 conv, stride 1  -> (64, 60, 60)
    GAP:        global average pool             -> (1, 128)
    Classifier: FC 128 -> 10
"""

import time
import ctypes
import numpy as np

np.random.seed(42)

# ---------------------------------------------------------------------------
# GPA helper
# ---------------------------------------------------------------------------
gpa = ctypes.CDLL("./libgpa_helper.so")
gpa.virt_to_phys.argtypes = [ctypes.c_void_p]
gpa.virt_to_phys.restype  = ctypes.c_ulong

def print_gpa(name, arr):
    addr = arr.ctypes.data
    phys = gpa.virt_to_phys(ctypes.c_void_p(addr))
    print(f"{name} GPA: 0x{phys:x}", flush=True)

# ---------------------------------------------------------------------------
# Marker pages
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
# Primitives
# ---------------------------------------------------------------------------
def relu(x):
    return np.maximum(x, 0)

def conv2d(x, kernels, bias):
    """Simple single-stride 2D convolution (no padding)."""
    out_channels        = kernels.shape[0]
    _, h, w             = x.shape
    kh, kw              = kernels.shape[2], kernels.shape[3]
    out_h, out_w        = h - kh + 1, w - kw + 1
    out = np.zeros((out_channels, out_h, out_w), dtype=np.float32)
    for oc in range(out_channels):
        for i in range(out_h):
            for j in range(out_w):
                out[oc, i, j] = np.sum(x[:, i:i+kh, j:j+kw] * kernels[oc]) + bias[oc]
    return out

def global_avg_pool(x):
    """Global average pool: (C, H, W) -> (1, C)."""
    return x.mean(axis=(1, 2), keepdims=False).reshape(1, -1)

def residual_block(x, kernels, bias):
    """
    Minimal residual block: conv -> relu -> conv, with identity shortcut.
    Shortcut is applied only when channel dimensions match.
    """
    out = relu(conv2d(x, kernels[0], bias[0]))
    out = conv2d(out, kernels[1], bias[1])
    # Crop x spatially to match out (no-padding conv shrinks spatial dims)
    _, oh, ow = out.shape
    _, xh, xw = x.shape
    ch = (xh - oh) // 2
    cw = (xw - ow) // 2
    shortcut = x[:out.shape[0], ch:ch+oh, cw:cw+ow] if x.shape[0] == out.shape[0] else 0
    return relu(out + shortcut)

# ---------------------------------------------------------------------------
# Model weights
# ---------------------------------------------------------------------------
# Block 1: two conv layers, 1->32 channels, 3x3 kernel
K1a = np.random.randn(32,  1, 3, 3).astype(np.float32)
b1a = np.random.randn(32).astype(np.float32)
K1b = np.random.randn(32, 32, 3, 3).astype(np.float32)
b1b = np.random.randn(32).astype(np.float32)

# Block 2: two conv layers, 32->64 channels, 3x3 kernel
K2a = np.random.randn(64, 32, 3, 3).astype(np.float32)
b2a = np.random.randn(64).astype(np.float32)
K2b = np.random.randn(64, 64, 3, 3).astype(np.float32)
b2b = np.random.randn(64).astype(np.float32)

# Classifier: FC 128 -> 10
W_fc = np.random.randn(128, 10).astype(np.float32)
b_fc = np.random.randn(10).astype(np.float32)

# Input: single-channel 64x64 image
X = np.random.randn(1, 64, 64).astype(np.float32)

# ---------------------------------------------------------------------------
# Marker pages
# ---------------------------------------------------------------------------
inf_start        = make_marker()
block1_start     = make_marker()
block1_end       = make_marker()
block2_start     = make_marker()
block2_end       = make_marker()
classifier_start = make_marker()
classifier_end   = make_marker()
termination      = make_marker()

# ---------------------------------------------------------------------------
# Print GPAs
# ---------------------------------------------------------------------------
print("MODEL: NUMPY_RESNET", flush=True)
print_gpa("Inference start marker",    inf_start)
print_gpa("Block 1 start marker",      block1_start)
print_gpa("Block 1 end marker",        block1_end)
print_gpa("Block 2 start marker",      block2_start)
print_gpa("Block 2 end marker",        block2_end)
print_gpa("Classifier start marker",   classifier_start)
print_gpa("Classifier end marker",     classifier_end)
print_gpa("Termination marker",        termination)

# ---------------------------------------------------------------------------
# Inference loop
# ---------------------------------------------------------------------------
i = 0
while True:
    print(f"INFERENCE {i} START", flush=True)
    touch_marker(inf_start)

    # Residual block 1
    touch_marker(block1_start)
    h = residual_block(X, [K1a, K1b], [b1a, b1b])
    touch_marker(block1_end)

    # Residual block 2
    touch_marker(block2_start)
    h = residual_block(h, [K2a, K2b], [b2a, b2b])
    touch_marker(block2_end)

    # Global average pool + classifier
    touch_marker(classifier_start)
    h = global_avg_pool(h)
    y = h @ W_fc + b_fc
    touch_marker(classifier_end)

    print(f"INFERENCE {i} END", flush=True)
    touch_marker(termination)

    time.sleep(0.5)
    i += 1