# HULA Flow Completion Time (FCT) Telemetry Guide

This guide explains how to implement and monitor Flow Completion Time (FCT) in your HULA load balancing network.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Implementation Details](#implementation-details)
4. [Usage](#usage)
5. [Output Format](#output-format)
6. [Analysis and Visualization](#analysis-and-visualization)
7. [Troubleshooting](#troubleshooting)

---

## Overview

Flow Completion Time (FCT) measures the time elapsed from the first packet of a flow to the last packet, indicating how long a flow takes to complete.

### Key Metrics

- **Per-Packet FCT**: Time from flow start to current packet: `FCT = flow_current_time - flow_start_time`
- **Flow-Level FCT**: Aggregated from all packets: `Flow FCT = max(timestamp) - min(timestamp)`
- **Unit**: Nanoseconds (can convert to µs or ms)

### Why FCT Matters

✅ **Measure load balancing effectiveness**: Lower FCT = better performance  
✅ **Detect congestion**: Long FCT indicates bottlenecks  
✅ **Classify flows**: Short/Medium/Long flows help analysis  
✅ **SLA verification**: Ensure service levels are met  

---

## Architecture

### Data Plane (P4)

```
┌──────────────────────────────────┐
│ Ingress Pipeline                 │
│ 1. Hash packet to flow ID         │
│ 2. Read flow_start_time register  │
│ 3. If new flow: store timestamp   │
│ 4. Put start & current times in   │
│    telemetry header              │
└──────────────┬──────────────────┘
               │
               ▼
        ┌─────────────┐
        │  Buffer     │
        │  (Queue)    │
        └──────┬──────┘
               │
               ▼
┌──────────────────────────────────┐
│ Egress Pipeline                  │
│ 1. Read queue_depth              │
│ 2. Populate egress fields        │
└──────────────┬──────────────────┘
               │
               ▼
        ┌─────────────────────┐
        │ Deparser            │
        │ Emit all telemetry  │
        └─────────┬───────────┘
               │
               ▼
    ┌──────────────────────┐
    │ Network              │
    │ (Telemetry Header)   │
    └──────────┬───────────┘
               │
               ▼
┌──────────────────────────────────┐
│ Receiver (fct_receiver.py)       │
│ 1. Parse HULA telemetry         │
│ 2. Extract timestamps           │
│ 3. Compute FCT per packet       │
│ 4. Write to CSV                 │
└──────────────────────────────────┘
```

---

## Implementation Details

### 1. HULA Header with FCT Fields

```p4
header hula_t {
    // ... existing path entries ...
    bit<8>  queue_depth;           // Queue depth telemetry
    
    // NEW: FCT Tracking Fields
    bit<48> flow_start_time;       // Timestamp of first packet in flow
    bit<48> flow_current_time;     // Timestamp of current packet
}
```

**Field Sizes:**
- `flow_start_time`: 48-bit (nanoseconds) = ~281 years range ✅
- `flow_current_time`: 48-bit (nanoseconds) = ~281 years range ✅
- Total telemetry header: 17 + 12 = 29 bytes

### 2. Flow Tracking Register

```p4
// Store the first packet timestamp per flow (indexed by flow hash)
register<time_t>((bit<32>) 1024) flow_start_time_reg;

// time_t is typedef'd as bit<48>
```

**Register Size:**
- 1024 flows tracked simultaneously
- Each entry: 48 bits = 6 bytes
- Total: 6 KB memory

### 3. Flow Hash Computation

```p4
action track_flow_fct() {
    // Compute hash of 5-tuple
    bit<32> flow_hash;
    hash(flow_hash, HashAlgorithm.csum16, 32w0, {
        hdr.ipv4.srcAddr,
        hdr.ipv4.dstAddr,
        hdr.ipv4.protocol,
        hdr.tcp.srcPort,
        hdr.tcp.dstPort
    }, 32w1 << 10 - 1);  // 1024 buckets
    
    // Read flow start time from register
    time_t curr_time = standard_metadata.ingress_global_timestamp;
    time_t flow_start;
    flow_start_time_reg.read(flow_start, flow_hash);
    
    // If flow_start == 0, this is a new flow
    bool is_new_flow = (flow_start == 0);
    time_t start_time = is_new_flow ? curr_time : flow_start;
    flow_start_time_reg.write(flow_hash, start_time);
    
    // Store in telemetry header
    if (hdr.hula.isValid()) {
        hdr.hula.flow_start_time = start_time;
        hdr.hula.flow_current_time = curr_time;
    }
}
```

**Key Points:**
- ✅ Uses ingress timestamp (when packet arrives)
- ✅ Handles new vs. existing flows
- ✅ Small memory footprint (6 KB for 1024 flows)
- ✅ O(1) lookup performance

### 4. Type Casting

**Input**: `standard_metadata.ingress_global_timestamp` is `bit<48>`  
**Output**: `hdr.hula.flow_start_time` and `hdr.hula.flow_current_time` are `bit<48>`

```p4
// ✅ CORRECT: Direct assignment (same bit width)
bit<48> curr_time = standard_metadata.ingress_global_timestamp;
hdr.hula.flow_start_time = start_time;
hdr.hula.flow_current_time = curr_time;
```

No casting needed—already the same width! ✅

---

## Usage

### Step 1: Build P4 Program

```bash
cd /home/vboxuser/Pictures/Hula-hoop_small.bkp
make clean && make
```

### Step 2: Run Controller

```bash
./controller.py
```

### Step 3: Start FCT Receiver

```bash
# On a receiving host (e.g., h9)
sudo python3 test-scripts/fct_receiver.py -o fct_data.csv
```

### Step 4: Generate Traffic

```bash
# On a sending host (e.g., h1)
iperf -c 10.0.9.1 -b 50M -t 30
```

### Step 5: Analyze Results

```bash
# Stop receiver (Ctrl+C)

# Analyze
python3 test-scripts/analyze_fct.py -i fct_data.csv

# With visualization
python3 test-scripts/analyze_fct.py -i fct_data.csv --graph fct_output.png
```

---

## Output Format

### CSV File Structure

**Filename:** `fct_telemetry.csv`

**Columns:**

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| timestamp_s | float | Seconds since receiver start | 0.125 |
| src_ip | string | Source IP | 10.0.1.1 |
| dst_ip | string | Destination IP | 10.0.9.1 |
| src_port | int | Source port | 50000 |
| dst_port | int | Destination port | 5001 |
| protocol | string | Transport (TCP/UDP) | TCP |
| flow_id | string | Flow identifier | 10.0.1.1:50000→10.0.9.1:5001/TCP |
| flow_start_time_ns | int | First packet timestamp (ns) | 1234567890 |
| flow_current_time_ns | int | Current packet timestamp (ns) | 1234567900 |
| fct_ns | int | FCT in nanoseconds | 10 |
| fct_us | float | FCT in microseconds | 10.5 |
| fct_ms | float | FCT in milliseconds | 0.0105 |
| queue_depth_bytes | int | Egress queue depth | 45 |
| datetime_iso | string | ISO 8601 timestamp | 2024-01-15T10:30:45.123456 |

### Example Data

```csv
timestamp_s,src_ip,dst_ip,src_port,dst_port,protocol,flow_id,flow_start_time_ns,flow_current_time_ns,fct_ns,fct_us,fct_ms,queue_depth_bytes,datetime_iso
0.000,10.0.1.1,10.0.9.1,50000,5001,TCP,10.0.1.1:50000→10.0.9.1:5001/TCP,1000000000,1000000000,0,0.0,0.0,0,2024-01-15T10:30:45.000
0.005,10.0.1.1,10.0.9.1,50000,5001,TCP,10.0.1.1:50000→10.0.9.1:5001/TCP,1000000000,1000000500,500,0.5,0.0005,12,2024-01-15T10:30:45.005
0.010,10.0.1.1,10.0.9.1,50000,5001,TCP,10.0.1.1:50000→10.0.9.1:5001/TCP,1000000000,1000001200,1200,1.2,0.0012,45,2024-01-15T10:30:45.010
0.015,10.0.1.1,10.0.9.1,50000,5001,TCP,10.0.1.1:50000→10.0.9.1:5001/TCP,1000000000,1000002500,2500,2.5,0.0025,67,2024-01-15T10:30:45.015
0.020,10.0.1.2,10.0.9.2,50001,5001,TCP,10.0.1.2:50001→10.0.9.2:5001/TCP,1000050000,1000050800,800,0.8,0.0008,23,2024-01-15T10:30:45.020
```

### Interpretation Guide

| FCT (milliseconds) | Status | Meaning |
|-------------------|--------|---------|
| 0 | ✅ Minimal | Packet arrived and left immediately |
| 0.001-0.01 | ✅ Short | Good performance, no congestion |
| 0.01-0.1 | ⚠️ Medium | Moderate latency, acceptable |
| 0.1-1.0 | 🔴 Long | Significant delay, investigate |
| >1.0 | 🔴 Very Long | Severe congestion or retransmissions |

---

## Analysis and Visualization

### Global Statistics

```bash
python3 test-scripts/analyze_fct.py -i fct_data.csv
```

**Output:**
```
================================================================================
GLOBAL FLOW COMPLETION TIME (FCT) STATISTICS
================================================================================
  Total Samples:         5000
  Min FCT:               0.000001 ms
  Max FCT:               2.345600 ms
  Avg FCT:               0.125432 ms
  Median FCT:            0.089456 ms
  Std Dev:               0.234567 ms
  50th Percentile (P50): 0.089456 ms
  95th Percentile (P95): 0.567890 ms
  99th Percentile (P99): 1.234567 ms
```

### Flow Classification

```
SHORT (<10ms)     : 4800 (96.0%) ████████████████████████████████████████████████
MEDIUM (<100ms)   :  180 ( 3.6%) ██
LONG (<1000ms)    :   19 ( 0.4%)
VERY_LONG (>1000ms):  1  ( 0.0%)
```

### Per-Flow Analysis

```
Top 10 flows by average FCT:

  1. 10.0.1.5:50005→10.0.9.5:5001/TCP
     Packets:  523, Avg FCT: 0.567890 ms, Min/Max: 0.001/2.345 ms, Total: 2.345 ms

  2. 10.0.1.3:50003→10.0.9.3:5001/TCP
     Packets:  487, Avg FCT: 0.234567 ms, Min/Max: 0.001/1.234 ms, Total: 1.234 ms
```

### Matplotlib Visualization

```bash
python3 test-scripts/analyze_fct.py -i fct_data.csv --graph fct_visual.png
```

**Generates 4 plots:**
1. **FCT Timeline**: Shows FCT over time with trend
2. **FCT Histogram**: Distribution of FCT values
3. **FCT vs Queue Depth**: Scatter plot showing correlation
4. **CDF**: Cumulative distribution with percentile markers

---

## Troubleshooting

### Issue 1: All FCT Values are 0

**Cause:** flow_start_time register not persisting between packets  
**Solution:**
1. Verify register declaration: `register<time_t>(...) 1024) flow_start_time_reg;`
2. Check flow hash computation is deterministic
3. Ensure track_flow_fct() is called for every packet

### Issue 2: FCT Jumps to Very Large Values

**Cause:** Flow register reset or collision in hash table  
**Solution:**
1. Increase register size: change `1024` to `4096` or `8192`
2. Use better hash function (CRC, etc.)
3. Add flow state tracking to detect resets

### Issue 3: Real FCT Is Longer Than Expected

**Cause:** End-to-end latency includes:
- Serialization delay (packet size / link speed)
- Propagation delay (distance)
- Queue delay (at each hop)
- Processing delay (at each hop)

**Solution:**
1. Analyze FCT vs queue_depth correlation
2. Compare with baseline (single-hop) latency
3. Check path taken (ECMP might vary)

### Issue 4: Receiver Doesn't See FCT Fields

**Cause:** Hula class definition mismatch or packet parsing error  
**Solution:**
1. Verify Hula class has both flow_start_time and flow_current_time fields
2. Check field order matches P4 header
3. Test with tcpdump: `tcpdump -i eth0 -XX proto 66`

---

## Performance & Resource Impact

### Data Plane

- **Memory**: 6 KB per 1024 concurrent flows
- **CPU**: O(1) hash calculation + 2 register ops per packet
- **Latency**: < 1 µs additional (hardware processing)
- **Throughput**: No impact (parallel processing)

### Telemetry Header

- **Overhead**: +12 bytes per packet (flow_start_time + flow_current_time)
- **Payload Impact**: < 1% for typical packets

### Receiver

- **CPU**: Hash computation per packet
- **Memory**: CSV buffering
- **I/O**: Sequential file writes (optimized)

---

## Advanced Usage

### Custom Flow Classification

```bash
# Classify flows as:
# - SHORT:     < 50ms
# - MEDIUM:    < 500ms  
# - LONG:      < 5000ms
# - VERY_LONG: >= 5000ms
python3 test-scripts/analyze_fct.py -i fct_data.csv \
  --short 50 --medium 500 --long 5000
```

### Correlation Analysis

Use Jupyter notebook for advanced analysis:

```python
import pandas as pd
import matplotlib.pyplot as plt

# Load data
df = pd.read_csv('fct_data.csv')

# Correlation: FCT vs Queue Depth
correlation = df['fct_ms'].corr(df['queue_depth_bytes'])
print(f"Correlation: {correlation:.3f}")

# Plot
plt.scatter(df['queue_depth_bytes'], df['fct_ms'], alpha=0.5)
plt.xlabel('Queue Depth (bytes)')
plt.ylabel('FCT (ms)')
plt.title(f'FCT vs Queue Depth (r={correlation:.3f})')
plt.show()
```

---

## Bonus: Export to Other Tools

### Convert to Pandas DataFrame

```python
import pandas as pd

df = pd.read_csv('fct_data.csv')
print(df.describe())
```

### Plot with Plotly (Interactive)

```python
import plotly.express as px
import pandas as pd

df = pd.read_csv('fct_data.csv')
fig = px.scatter(df, x='queue_depth_bytes', y='fct_ms', 
                 color='flow_id', title='FCT Analysis')
fig.show()
```

### Export to JSON

```python
import pandas as pd
import json

df = pd.read_csv('fct_data.csv')
df.to_json('fct_data.json', orient='records')
```

---

## Summary

**What FCT Tracks:**
- ✅ Per-packet flow start time
- ✅ Per-packet current time
- ✅ Implicit FCT: current - start
- ✅ Correlation with queue depth

**How It Works:**
1. **Ingress**: Hash flow, read/write start time register
2. **Telemetry**: Embed start and current timestamps
3. **Egress**: Add queue depth
4. **Deparser**: Emit telemetry header
5. **Receiver**: Compute FCT and write to CSV
6. **Analysis**: Statistics, visualization, classification

**Performance:**
- Minimal memory (6 KB for 1024 flows)
- No speed impact (hardware processing)
- Clean CSV output for analysis

**Key Insights:**
- P50 FCT: Typical flow latency
- P95/P99 FCT: Tail latency (SLA critical)
- FCT vs queue_depth: Shows load correlation
- Flow classification: Identifies problematic flows

Happy monitoring! 📊
