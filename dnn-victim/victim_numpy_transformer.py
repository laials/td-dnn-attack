"""
victim_numpy_transformer.py

NumPy Mini Transformer victim for the TDXRay DNN side-channel attack.
Implements a single transformer encoder block in pure NumPy.

Markers:
    INF_START / TERM              - inference boundaries
    QKV_START / QKV_END           - QKV projection (attention head weights)
    ATTENTION_START / ATTENTION_END - scaled dot-product attention
    FFN_START / FFN_END           - feed-forward network
    CLASSIFIER_START / END        - output projection

Architecture (all float32):
    Input:      (seq_len=8, d_model=384)
    QKV:        3 x (384 -> 384) projections
    Attention:  multi-head, 6 heads, head_dim=64
    FFN:        384 -> 1536 -> 384
    Classifier: 384 -> 10
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
# Transformer primitives
# ---------------------------------------------------------------------------
def softmax(x):
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)

def layer_norm(x, gamma, beta, eps=1e-5):
    mean = x.mean(axis=-1, keepdims=True)
    std  = x.std(axis=-1,  keepdims=True)
    return gamma * (x - mean) / (std + eps) + beta

def relu(x):
    return np.maximum(x, 0)

def scaled_dot_product_attention(Q, K, V):
    """Q, K, V: (seq_len, head_dim)"""
    d_k    = Q.shape[-1]
    scores = Q @ K.T / np.sqrt(d_k)
    weights = softmax(scores)
    return weights @ V

def multi_head_attention(x, W_q, W_k, W_v, W_o, num_heads, head_dim):
    """
    x:     (seq_len, d_model)
    W_q/k/v: (d_model, d_model)
    W_o:   (d_model, d_model)
    """
    seq_len, d_model = x.shape

    Q = x @ W_q   # (seq_len, d_model)
    K = x @ W_k
    V = x @ W_v

    # Split into heads
    Q = Q.reshape(seq_len, num_heads, head_dim).transpose(1, 0, 2)
    K = K.reshape(seq_len, num_heads, head_dim).transpose(1, 0, 2)
    V = V.reshape(seq_len, num_heads, head_dim).transpose(1, 0, 2)

    # Attention per head
    heads = np.zeros((num_heads, seq_len, head_dim), dtype=np.float32)
    for h in range(num_heads):
        heads[h] = scaled_dot_product_attention(Q[h], K[h], V[h])

    # Concatenate and project
    concat = heads.transpose(1, 0, 2).reshape(seq_len, d_model)
    return concat @ W_o

# ---------------------------------------------------------------------------
# Model parameters
# ---------------------------------------------------------------------------
SEQ_LEN   = 8
D_MODEL   = 384
NUM_HEADS = 6
HEAD_DIM  = D_MODEL // NUM_HEADS   # 64
FFN_DIM   = 1536
NUM_CLASSES = 10

# QKV projection weights
W_q = np.random.randn(D_MODEL, D_MODEL).astype(np.float32)
W_k = np.random.randn(D_MODEL, D_MODEL).astype(np.float32)
W_v = np.random.randn(D_MODEL, D_MODEL).astype(np.float32)
W_o = np.random.randn(D_MODEL, D_MODEL).astype(np.float32)

# Layer norms
gamma1 = np.ones(D_MODEL,  dtype=np.float32)
beta1  = np.zeros(D_MODEL, dtype=np.float32)
gamma2 = np.ones(D_MODEL,  dtype=np.float32)
beta2  = np.zeros(D_MODEL, dtype=np.float32)

# FFN weights
W_ffn1 = np.random.randn(D_MODEL, FFN_DIM).astype(np.float32)
b_ffn1 = np.random.randn(FFN_DIM).astype(np.float32)
W_ffn2 = np.random.randn(FFN_DIM, D_MODEL).astype(np.float32)
b_ffn2 = np.random.randn(D_MODEL).astype(np.float32)

# Classifier
W_cls = np.random.randn(D_MODEL, NUM_CLASSES).astype(np.float32)
b_cls = np.random.randn(NUM_CLASSES).astype(np.float32)

# Input token embeddings
X = np.random.randn(SEQ_LEN, D_MODEL).astype(np.float32)

# ---------------------------------------------------------------------------
# Marker pages
# ---------------------------------------------------------------------------
inf_start        = make_marker()
qkv_start        = make_marker()
qkv_end          = make_marker()
attention_start  = make_marker()
attention_end    = make_marker()
ffn_start        = make_marker()
ffn_end          = make_marker()
classifier_start = make_marker()
classifier_end   = make_marker()
termination      = make_marker()

# ---------------------------------------------------------------------------
# Print GPAs
# ---------------------------------------------------------------------------
print("MODEL: NUMPY_TRANSFORMER", flush=True)
print_gpa("Inference start marker",    inf_start)
print_gpa("QKV start marker",          qkv_start)
print_gpa("QKV end marker",            qkv_end)
print_gpa("Attention start marker",    attention_start)
print_gpa("Attention end marker",      attention_end)
print_gpa("FFN start marker",          ffn_start)
print_gpa("FFN end marker",            ffn_end)
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

    # QKV projections
    touch_marker(qkv_start)
    Q = X @ W_q
    K = X @ W_k
    V = X @ W_v
    touch_marker(qkv_end)

    # Multi-head attention
    touch_marker(attention_start)
    attn_out = multi_head_attention(X, W_q, W_k, W_v, W_o, NUM_HEADS, HEAD_DIM)
    x_attn   = layer_norm(X + attn_out, gamma1, beta1)
    touch_marker(attention_end)

    # Feed-forward network
    touch_marker(ffn_start)
    ffn_out = relu(x_attn @ W_ffn1 + b_ffn1) @ W_ffn2 + b_ffn2
    x_ffn   = layer_norm(x_attn + ffn_out, gamma2, beta2)
    touch_marker(ffn_end)

    # Classifier on first token
    touch_marker(classifier_start)
    y = x_ffn[0:1] @ W_cls + b_cls
    touch_marker(classifier_end)

    print(f"INFERENCE {i} END", flush=True)
    touch_marker(termination)

    time.sleep(0.5)
    i += 1