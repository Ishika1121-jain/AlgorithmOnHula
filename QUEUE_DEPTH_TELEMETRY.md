# HULA Queue Depth Telemetry Guide

This guide explains how to add and monitor queue depth telemetry in the HULA (Head-first Unicast and multicast Load-balancing Architecture) project.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Implementation Details](#implementation-details)
4. [Usage](#usage)
5. [Output Format](#output-format)
6. [Analysis and Visualization](#analysis-and-visualization)
7. [Type Casting & Error Handling](#type-casting--error-handling)

---

## Overview

Queue depth telemetry provides real-time visibility into packet queue occupancy at egress ports. This helps:
- **Monitor congestion**: Detect when queues build up
- **Analyze performance**: Understand latency patterns
- **Validate HULA**: Verify load balancing effectiveness
- **Optimize**: Identify bottlenecks in the network

### Key Features

✅ **8-bit queue depth field** (0-255 bytes) in HULA telemetry header  
✅ **Per-packet capture** at egress queue departure  
✅ **Automatic saturation** at 255 bytes for queue depths > 255  
✅ **CSV storage** with flow identification  
✅ **Congestion detection** and visualization  

---

## Architecture

### Data Plane (P4)

```
┌─────────────────────────────────────────────┐
│ Ingress Pipeline                            │
│  - Parse HULA header                        │
│  - Process HULA logic                       │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ Egress Queue                                │
│  - Packet waits in queue                    │
│  - Queue depth changes dynamically          │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ Egress Pipeline                             │
│  - Read: standard_metadata.deq_qdepth       │
│  - Cast to bit<8>                           │
│  - Write to hdr.hula.queue_depth            │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ Deparser                                    │
│  - Emit: packet.emit(hdr.hula)              │
│  - Include queue_depth in output packet     │
└─────────────┬───────────────────────────────┘
              │
              ▼
    ┌─────────────────────┐
    │  Network            │
    │  (Receiver-side)    │
    └─────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ Receiver (telemetry_receiver.py)            │
│  - Sniff packets                            │
│  - Parse HULA header                        │
│  - Extract queue_depth + flow info          │
│  - Write to CSV                             │
└─────────────────────────────────────────────┘
```

### Control Plane (Controller + Receiver)

The controller (`controller.py`) configures the data plane, and the receiver script (`telemetry_receiver.py`) collects telemetry from the network.

---

## Implementation Details

### 1. P4 Header Definition

**File:** `switch.p4`

```p4
header hula_t {
    bit<24> dst_tor0;
    bit<8>  path_util0;
    bit<24> dst_tor1;
    bit<8>  path_util1;
    bit<24> dst_tor2;
    bit<8>  path_util2;
    bit<24> dst_tor3;
    bit<8>  path_util3;
    bit<8>  queue_depth;  // NEW: Queue depth telemetry
}
```

**Field Details:**
- **queue_depth**: 8-bit unsigned integer (0-255 bytes)
- **Semantics**: Egress queue occupancy at packet departure time
- **Source**: `standard_metadata.deq_qdepth` (provided by BMv2 switch model)

### 2. Egress Pipeline Logic

**File:** `switch.p4` - `MyEgress` control

```p4
control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {
        // Populate queue_depth telemetry from egress queue occupancy
        if (hdr.hula.isValid()) {
            bit<32> queue_occ = standard_metadata.deq_qdepth;
            // Saturating cast: if queue > 255, cap at 255
            hdr.hula.queue_depth = (bit<8>)(queue_occ > 255 ? 255 : queue_occ);
        }
    }
}
```

**Key Points:**
- ✅ Only populated for **HULA packets** (hdu.hula.isValid())
- ✅ Reads egress queue occupancy from `standard_metadata.deq_qdepth`
- ✅ **Saturating cast** prevents overflow (0-255 range)
- ✅ Non-HULA packets are unaffected

### 3. Type Casting Explanation

**Problem:** `standard_metadata.deq_qdepth` is `bit<32>`, but `hdr.hula.queue_depth` is `bit<8>`

**Solution:** Use ternary operator for saturating cast:

```p4
// ❌ WRONG: Direct cast causes overflow
hdr.hula.queue_depth = (bit<8>)standard_metadata.deq_qdepth;  
// If deq_qdepth = 300, result = 44 (300 % 256) - INCORRECT!

// ✅ CORRECT: Saturating cast
hdr.hula.queue_depth = (bit<8>)(queue_occ > 255 ? 255 : queue_occ);
// If deq_qdepth = 300, result = 255 - CORRECT!
```

---

## Usage

### Step 1: Build the P4 Program

```bash
cd /home/vboxuser/Pictures/Hula-hoop_small.bkp
make clean
make
```

This compiles the P4 code and generates:
- `build/switch.p4info` - Pipeline info
- `build/switch.json` - BMv2 JSON

### Step 2: Run the Controller

```bash
./controller.py
```

The controller installs the P4 pipeline on the switches.

### Step 3: Start Telemetry Collection

In a **different terminal** on a receiving host (e.g., h9):

```bash
# Make script executable
chmod +x test-scripts/telemetry_receiver.py

# Run receiver (collects in background)
python3 test-scripts/telemetry_receiver.py -o telemetry_data.csv &
```

**Options:**
```
-o, --output FILE        Output CSV file (default: queue_depth_telemetry.csv)
-p, --show-probes        Include probe packets in output (optional)
```

### Step 4: Send Traffic

In the mininet CLI, start traffic from another host:

```
mininet> xterm h1
# In h1 terminal
python3 test-scripts/send.py -d h9
```

Or use `iperf` for continuous traffic:

```bash
# Terminal 1: Receiver (h9)
iperf -s -u -i 1

# Terminal 2: Sender (h1)
iperf -c h9 -u -b 50M -t 30
```

### Step 5: Stop and Analyze

```bash
# Press Ctrl+C to stop telemetry receiver
# or send SIGTERM from another terminal

# Analyze the collected data
python3 test-scripts/analyze_telemetry.py -i telemetry_data.csv

# Generate visualization (if matplotlib available)
python3 test-scripts/analyze_telemetry.py -i telemetry_data.csv --graph qd_graph.png
```

---

## Output Format

### CSV File Structure

**Filename:** `queue_depth_telemetry.csv`

**Columns:**

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| timestamp_s | float | Seconds since receiver start | 0.125 |
| src_ip | string | Source IP address | 10.0.1.1 |
| dst_ip | string | Destination IP address | 10.0.9.1 |
| src_port | int | TCP/UDP source port | 50000 |
| dst_port | int | TCP/UDP destination port | 5001 |
| protocol | string | Transport protocol | TCP/UDP/PROBE |
| queue_depth_bytes | int | Egress queue depth | 45 |
| flow_hash | string | Flow ID hash (8 chars) | a1b2c3d4 |
| datetime_iso | string | ISO 8601 timestamp | 2024-01-15T10:30:45.123456 |

### Example Data

```csv
timestamp_s,src_ip,dst_ip,src_port,dst_port,protocol,queue_depth_bytes,flow_hash,datetime_iso
0.000,10.0.1.1,10.0.9.1,50000,5001,TCP,0,a1b2c3d4,2024-01-15T10:30:45.000000
0.002,10.0.1.1,10.0.9.1,50000,5001,TCP,5,a1b2c3d4,2024-01-15T10:30:45.002000
0.005,10.0.1.1,10.0.9.1,50000,5001,TCP,12,a1b2c3d4,2024-01-15T10:30:45.005000
0.008,10.0.1.2,10.0.9.2,50001,5001,TCP,3,e5f6g7h8,2024-01-15T10:30:45.008000
0.010,10.0.1.1,10.0.9.1,50000,5001,TCP,45,a1b2c3d4,2024-01-15T10:30:45.010000
0.015,10.0.1.1,10.0.9.1,50000,5001,TCP,67,a1b2c3d4,2024-01-15T10:30:45.015000
0.020,10.0.1.1,10.0.9.1,50000,5001,TCP,89,a1b2c3d4,2024-01-15T10:30:45.020000
0.025,10.0.1.1,10.0.9.1,50000,5001,TCP,102,a1b2c3d4,2024-01-15T10:30:45.025000
0.030,10.0.1.1,10.0.9.1,50000,5001,TCP,115,a1b2c3d4,2024-01-15T10:30:45.030000
```

### Interpretation

- **queue_depth_bytes = 0**: Queue is empty
- **queue_depth_bytes = 5-50**: Normal operation
- **queue_depth_bytes = 100+**: Potential congestion
- **queue_depth_bytes = 255**: Queue deeply congested OR actual depth > 255 bytes

---

## Analysis and Visualization

### Quick Statistics

```bash
python3 test-scripts/analyze_telemetry.py -i telemetry_data.csv
```

**Output:**
```
================================================================================
GLOBAL QUEUE DEPTH STATISTICS
================================================================================
  Total Samples:     1250
  Min Queue Depth:   0 bytes
  Max Queue Depth:   189 bytes
  Avg Queue Depth:   45.32 bytes
  Median:            42 bytes
  Std Dev:           38.91 bytes
  95th Percentile:   125 bytes
  99th Percentile:   167 bytes

================================================================================
PER-FLOW QUEUE DEPTH STATISTICS
================================================================================

Top 10 flows by average queue depth:

  1. 10.0.1.1:50000->10.0.9.1:5001
     Samples: 520
     Avg:     67.84 bytes
     Min/Max: 0/189 bytes

  2. 10.0.1.2:50001->10.0.9.2:5001
     Samples: 480
     Avg:     38.25 bytes
     Min/Max: 0/145 bytes
```

### Matplotlib Visualization

```bash
python3 test-scripts/analyze_telemetry.py -i telemetry_data.csv --graph output.png
```

**Generates two plots:**
1. **Queue Depth Timeline**: Shows queue depth over time with shaded area
2. **Histogram**: Distribution of queue depths

### Congestion Detection

```bash
python3 test-scripts/analyze_telemetry.py -i telemetry_data.csv --threshold 150
```

**Output:**
```
================================================================================
CONGESTION DETECTION
================================================================================
Threshold: 150 bytes

Found 3 congestion period(s):

  Period 1:
    Time:     2.34s - 5.67s
    Duration: 3.33s
    Peak:     189 bytes
```

---

## Type Casting & Error Handling

### Common Issues and Solutions

#### Issue 1: "Cannot cast implicitly type 'bit<8>'"

**Error:** Direct cast of `bit<32>` to `bit<8>` fails

```p4
// ❌ WRONG
hdr.hula.queue_depth = (bit<8>)standard_metadata.deq_qdepth;
```

**Solution:** Use saturating cast with ternary operator

```p4
// ✅ CORRECT
bit<32> queue_occ = standard_metadata.deq_qdepth;
hdr.hula.queue_depth = (bit<8>)(queue_occ > 255 ? 255 : queue_occ);
```

#### Issue 2: Queue Depth Only Shows 0

**Cause:** Reading at wrong point (ingress vs. egress)

```p4
// ❌ WRONG: In ingress
if (hdr.hula.isValid()) {
    // enq_qdepth is queue depth at ENQUEUE, already in flight packets in queue
    hdr.hula.queue_depth = (bit<8>)standard_metadata.enq_qdepth;
}
```

**Solution:** Read in egress at dequeue time

```p4
// ✅ CORRECT: In egress
if (hdr.hula.isValid()) {
    // deq_qdepth is queue depth at DEQUEUE, shows congestion at departure
    hdr.hula.queue_depth = (bit<8>)(
        standard_metadata.deq_qdepth > 255 ? 255 : standard_metadata.deq_qdepth
    );
}
```

#### Issue 3: CSV File Contains All Zeros

**Cause:** Telemetry header not being emitted by deparser

**Solution:** Verify deparser includes `packet.emit(hdr.hula);`

```p4
control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.tcp);
        packet.emit(hdr.hula);  // ✅ MUST be present
    }
}
```

#### Issue 4: Receiver Script Not Seeing HULA Header

**Cause:** Port mirroring not configured or receiver on wrong interface

```bash
# Check if interface is actually receiving packets
tcpdump -i <interface> -nn | grep -E 'proto 66'

# Or sniff all traffic
python3 test-scripts/receive.py --show-probes
```

---

## Debugging Checklist

- [ ] P4 compiled successfully: `make` completes without errors
- [ ] Controller runs without errors: `./controller.py`
- [ ] HULA header definition includes `queue_depth` field
- [ ] Egress control block has queue_depth population logic
- [ ] Deparser emits HULA header
- [ ] Receiver script has updated Hula class with queue_depth field
- [ ] Traffic is flowing (use `iperf` or `send.py`)
- [ ] Receiver sees HULA packets: `tcpdump -i eth0 proto 66`
- [ ] CSV file is being written to: `tail -f queue_depth_telemetry.csv`

---

## Performance Impact

- **Minimal overhead**: One 8-bit field per HULA packet
- **CPU impact**: Negligible (single ternary comparison in egress)
- **Memory impact**: +1 byte per HULA packet in flight
- **Throughput impact**: None (hardware processing)

---

## Summary

This queue depth telemetry system provides:

✅ **Real-time visibility** into congestion patterns  
✅ **Easy CSV export** for post-processing  
✅ **Flow-level insights** for per-flow analysis  
✅ **Automatic congestion detection**  
✅ **Visualization tools** built-in  

The implementation is robust with:
- Saturating cast to prevent overflow
- Header validity checks
- Clean CSV formatting
- Comprehensive analysis tools

Happy monitoring! 📊
