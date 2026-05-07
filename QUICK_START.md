# Queue Depth Telemetry - Quick Start Guide

## Files Modified

### 1. **switch.p4** - P4 Data Plane

#### Change 1: Add `queue_depth` field to HULA header

**Location:** Header definitions (line ~35)

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
    bit<8>  queue_depth;  // ← NEW: 8-bit queue depth field
}
```

#### Change 2: Populate `queue_depth` in Egress Pipeline

**Location:** MyEgress control block (line ~500)

```p4
control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {
        // NEW: Populate queue_depth telemetry
        if (hdr.hula.isValid()) {
            bit<32> queue_occ = standard_metadata.deq_qdepth;
            // Saturating cast: cap at 255
            hdr.hula.queue_depth = (bit<8>)(queue_occ > 255 ? 255 : queue_occ);
        }
    }
}
```

✅ **Deparser already emits HULA header** - no changes needed!

---

### 2. **test-scripts/probe.py** - Probe Packet Generator

#### Change 1: Update Scapy Hula class definition

```diff
  class Hula(Packet):
      fields_desc = [
          BitField("dst_tor0", 0, 24),
          BitField("path_util0", 0, 8),
          BitField("dst_tor1", 0, 24),
          BitField("path_util1", 0, 8),
          BitField("dst_tor2", 0, 24),
          BitField("path_util2", 0, 8),
          BitField("dst_tor3", 0, 24),
          BitField("path_util3", 0, 8),
+         BitField("queue_depth", 0, 8),  # NEW: Queue depth
      ]
```

#### Change 2: Initialize queue_depth in probe packet

```diff
  pkt = pkt / Hula(
      dst_tor0=dt, path_util0=0,
      dst_tor1=dt+1, path_util1=0,
      dst_tor2=dt+2, path_util2=0,
      dst_tor3=dt+3, path_util3=0,
+     queue_depth=0  # NEW: Initialize (populated by switch)
  )
```

---

### 3. **test-scripts/receive.py** - Basic Receiver

#### Change: Update Scapy Hula class definition

```diff
  class Hula(Packet):
      fields_desc = [
-         BitField("dst_tor", 0, 24),
-         BitField("path_util", 0, 8)
+         BitField("dst_tor0", 0, 24),
+         BitField("path_util0", 0, 8),
+         BitField("dst_tor1", 0, 24),
+         BitField("path_util1", 0, 8),
+         BitField("dst_tor2", 0, 24),
+         BitField("path_util2", 0, 8),
+         BitField("dst_tor3", 0, 24),
+         BitField("path_util3", 0, 8),
+         BitField("queue_depth", 0, 8),  # NEW: Queue depth telemetry
      ]
```

---

### 4. **NEW: test-scripts/telemetry_receiver.py**

Advanced receiver script that:
- Captures HULA packets with queue_depth
- Extracts flow information (src/dst IP, ports)
- Writes structured CSV with timestamp, flow ID, and queue_depth
- Handles saturation (queue_depth capped at 255)
- Supports show-probes flag

**Usage:**
```bash
python3 test-scripts/telemetry_receiver.py -o telemetry_data.csv
# or with probes
python3 test-scripts/telemetry_receiver.py -o telemetry_data.csv --show-probes
```

**CSV Output Format:**
```
timestamp_s,src_ip,dst_ip,src_port,dst_port,protocol,queue_depth_bytes,flow_hash,datetime_iso
0.125,10.0.1.1,10.0.9.1,50000,5001,TCP,45,a1b2c3d4,2024-01-15T10:30:45.125
...
```

---

### 5. **NEW: test-scripts/analyze_telemetry.py**

Comprehensive analysis tool that provides:
- Global statistics (min, max, avg, P95, P99)
- Per-flow queue depth analysis
- Congestion period detection
- Text-based timeline graph
- Optional matplotlib visualization

**Usage:**
```bash
# Analyze data
python3 test-scripts/analyze_telemetry.py -i telemetry_data.csv

# With matplotlib graph
python3 test-scripts/analyze_telemetry.py -i telemetry_data.csv --graph output.png

# Custom threshold
python3 test-scripts/analyze_telemetry.py -i telemetry_data.csv --threshold 200
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
CONGESTION DETECTION
================================================================================
Found 3 congestion period(s):
  Period 1:
    Time:     2.34s - 5.67s
    Duration: 3.33s
    Peak:     189 bytes
```

---

### 6. **NEW: QUEUE_DEPTH_TELEMETRY.md**

Comprehensive documentation including:
- Architecture diagram
- Implementation details
- Type casting explanation
- Usage guide
- Output format specification
- Analysis and visualization
- Debugging checklist
- Common issues and solutions

---

## Key Implementation Decisions

### 1. **8-bit Queue Depth (0-255 bytes)**
- **Why?** Minimal header overhead while covering typical queue sizes
- **Saturation?** Yes - values > 255 are capped at 255
- **Semantics?** Egress queue occupancy at packet departure (deq_qdepth)

### 2. **Saturating Cast in P4**
```p4
hdr.hula.queue_depth = (bit<8>)(queue_occ > 255 ? 255 : queue_occ);
```
- Prevents overflow/wraparound
- Indicates "heavily congested" when at 255
- No silent data loss

### 3. **CSV Format**
- **Timestamp**: Seconds since receiver start (float)
- **Flow identification**: 5-tuple (src_ip:src_port → dst_ip:dst_port + protocol)
- **Flow hash**: 8-char MD5 hash for grouping flows
- **ISO datetime**: Human-readable reference timestamp

### 4. **Receiver-side Processing**
- Receives "raw" queue depth from switches
- Extracts IP/TCP/UDP headers for flow context
- Computes flow hash for analysis
- Streams to CSV (no buffering)

---

## Testing Workflow

### 1. Compile P4
```bash
cd /home/vboxuser/Pictures/Hula-hoop_small.bkp
make clean
make
```

### 2. Start Controller
```bash
./controller.py
```

### 3. Open Mininet CLI
```bash
# In another terminal
mininet
```

### 4. Start Telemetry Receiver (on receiving host)
```bash
mininet> xterm h9
# In h9 terminal
python3 test-scripts/telemetry_receiver.py -o telemetry.csv
```

### 5. Send Traffic
```bash
mininet> xterm h1
# In h1 terminal
python3 test-scripts/send.py -d h9
# or use iperf for sustained traffic
iperf -c h9 -u -b 50M -t 30
```

### 6. Analyze Data
```bash
# In a third terminal
python3 test-scripts/analyze_telemetry.py -i telemetry.csv
python3 test-scripts/analyze_telemetry.py -i telemetry.csv --graph output.png
```

---

## Expected Output Examples

### CSV Sample Data

```csv
timestamp_s,src_ip,dst_ip,src_port,dst_port,protocol,queue_depth_bytes,flow_hash,datetime_iso
0.000,10.0.1.1,10.0.9.1,50000,5001,TCP,0,a1b2c3d4,2024-01-15T10:30:45.000
0.002,10.0.1.1,10.0.9.1,50000,5001,TCP,5,a1b2c3d4,2024-01-15T10:30:45.002
0.005,10.0.1.1,10.0.9.1,50000,5001,TCP,12,a1b2c3d4,2024-01-15T10:30:45.005
0.010,10.0.1.1,10.0.9.1,50000,5001,TCP,45,a1b2c3d4,2024-01-15T10:30:45.010
0.015,10.0.1.1,10.0.9.1,50000,5001,TCP,67,a1b2c3d4,2024-01-15T10:30:45.015
0.020,10.0.1.1,10.0.9.1,50000,5001,TCP,89,a1b2c3d4,2024-01-15T10:30:45.020
0.025,10.0.1.1,10.0.9.1,50000,5001,TCP,102,a1b2c3d4,2024-01-15T10:30:45.025
0.030,10.0.1.1,10.0.9.1,50000,5001,TCP,115,a1b2c3d4,2024-01-15T10:30:45.030
```

### Interpretation
- **0 bytes**: Queue empty, no congestion
- **5-50 bytes**: Normal operation
- **50-150 bytes**: Moderate congestion
- **150+ bytes**: Heavy congestion
- **255 bytes**: Saturated (actual depth ≥ 255)

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| CSV only has 0s | deq_qdepth not populated | Check Telemetry in egress, verify deparser emits hula |
| Receiver sees no HULA packets | Port not mirrored or protocol 66 not sent | Verify traffic with `tcpdump proto 66`, check receiver interface |
| Type casting errors | Direct bit cast failure | Use saturating cast: `(bit<8>)(x > 255 ? 255 : x)` |
| Script fails "proto 66" | Scapy Hula header mismatch | Update class with all 4 entries + queue_depth |
| Empty CSV file | Receiver not seeing packets | Verify HULA packets are actually generated, check binding |

---

## Files Summary Table

| File | Type | Status | Purpose |
|------|------|--------|---------|
| [switch.p4](switch.p4) | Modified | ✅ Complete | P4 data plane with queue_depth support |
| [test-scripts/probe.py](test-scripts/probe.py) | Modified | ✅ Complete | Probe generator with queue_depth field |
| [test-scripts/receive.py](test-scripts/receive.py) | Modified | ✅ Complete | Basic receiver with queue_depth support |
| [test-scripts/telemetry_receiver.py](test-scripts/telemetry_receiver.py) | NEW | ✅ Complete | Advanced telemetry receiver with CSV output |
| [test-scripts/analyze_telemetry.py](test-scripts/analyze_telemetry.py) | NEW | ✅ Complete | Analysis and visualization tool |
| [QUEUE_DEPTH_TELEMETRY.md](QUEUE_DEPTH_TELEMETRY.md) | NEW | ✅ Complete | Comprehensive documentation |
| [QUICK_START.md](QUICK_START.md) | NEW | ✅ This File | Quick reference guide |

---

## What's Monitored

✅ **Per-packet queue depth** at egress  
✅ **Flow-level aggregation** for load balancing analysis  
✅ **Congestion periods** with automatic detection  
✅ **Per-flow statistics** (min, max, avg)  
✅ **Global network congestion** patterns  
✅ **Time-series data** for trend analysis  

---

## Next Steps

1. **Build:** `make clean && make`
2. **Deploy:** `./controller.py`
3. **Collect:** `python3 test-scripts/telemetry_receiver.py -o data.csv`
4. **Analyze:** `python3 test-scripts/analyze_telemetry.py -i data.csv --graph graph.png`
5. **Visualize:** Open `graph.png` or import CSV to Excel/Python

Enjoy monitoring! 📊
