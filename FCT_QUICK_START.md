# FCT Quick Start Guide

## 🚀 Get Flow Completion Time (FCT) Monitoring Running in 5 Minutes

### Prerequisites

You've already compiled the P4 program with FCT support (if not: `make clean && make`)

---

## 5-Step Quickstart

### Step 1: Start Controller (Terminal 1)

```bash
cd /home/vboxuser/Pictures/Hula-hoop_small.bkp
export PYTHONPATH=$PYTHONPATH:$(pwd)/build
./controller.py
```

✅ Wait for "Established as controller" messages

---

### Step 2: Start FCT Receiver (Terminal 2)

```bash
# On receiving host (e.g., h9) with sudo
sudo python3 test-scripts/fct_receiver.py -o fct_data.csv
```

📡 Receiver is now listening on eth0

---

### Step 3: Generate Traffic (Terminal 3)

```bash
# On sending host (e.g., h1)
iperf -c 10.0.9.1 -b 50M -t 30
```

🔄 Traffic is flowing for 30 seconds

---

### Step 4: Stop Receiver (after traffic ends)

```bash
# Press Ctrl+C in Terminal 2
# OR from Terminal 3:
pkill -f fct_receiver.py
```

✅ CSV file created: `fct_data.csv`

---

### Step 5: Analyze & Visualize

```bash
# Quick statistics
python3 test-scripts/analyze_fct.py -i fct_data.csv

# With visualization
python3 test-scripts/analyze_fct.py -i fct_data.csv --graph fct_visual.png
```

📊 Done! Check CSV and graphs

---

## 📋 One-Command Workflow

```bash
#!/bin/bash
# Terminal 1
./controller.py &

# Terminal 2 (after controller ready)
sudo python3 test-scripts/fct_receiver.py -o fct.csv &
FCT_PID=$!

# Terminal 3 (after receiver ready)
sleep 2
iperf -c 10.0.9.1 -b 50M -t 30

# After iperf completes
kill $FCT_PID
python3 test-scripts/analyze_fct.py -i fct.csv --graph fct_output.png
```

---

## 📊 Expected Output

### Console Output (FCT Receiver)

```
📡 Starting FCT telemetry receiver on interface: s206-eth2
📝 Output file: fct_data.csv
⏱️  Timestamp reference: 2026-04-11T14:25:17.681440
────────────────────────────────────────────────────────────────────────────────
[0.05s] 10.0.1.1:50000->10.0.9.1:5001/TCP                 | FCT:     0.025ms (   25.0µs) | Queue:   5B
[0.10s] 10.0.1.1:50000->10.0.9.1:5001/TCP                 | FCT:     0.123ms (  123.0µs) | Queue:  23B
[0.15s] 10.0.1.1:50000->10.0.9.1:5001/TCP                 | FCT:     0.456ms (  456.0µs) | Queue:  67B
[0.20s] 10.0.1.2:50001->10.0.9.2:5001/TCP                 | FCT:     0.089ms (   89.0µs) | Queue:  12B
```

### Analysis Output

```
================================================================================
GLOBAL FLOW COMPLETION TIME (FCT) STATISTICS
================================================================================
  Total Samples:         5000
  Min FCT:               0.000001 ms
  Max FCT:               2.345600 ms
  Avg FCT:               0.125432 ms
  Median FCT:            0.089456 ms
  95th Percentile (P95): 0.567890 ms
  99th Percentile (P99): 1.234567 ms

================================================================================
FLOW CLASSIFICATION BY FCT
================================================================================
  SHORT (<10ms)     : 4800 (96.0%) ████████████████████████████████
  MEDIUM (<100ms)   :  180 ( 3.6%) ██
  LONG (<1000ms)    :   19 ( 0.4%)
  VERY_LONG (>1000ms): 1  ( 0.0%)

================================================================================
PER-FLOW FCT ANALYSIS
================================================================================

Top 10 flows by average FCT:

  1. 10.0.1.5:50005->10.0.9.5:5001/TCP
     Packets:  523, Avg FCT: 0.567890 ms, Min/Max: 0.001/2.345 ms
```

---

## 🔧 Troubleshooting

| Problem | Solution |
|---------|----------|
| "Permission denied" | Use `sudo python3 ...` |
| "No eth interfaces" | Receiver should run inside mininet host |
| CSV is empty | Make sure iperf traffic is running |
| Large FCT values | Normal - includes full network RTT + queue delay |
| Script crashes | Install: `pip install scapy pandas matplotlib` |

---

## 📈 Analyzing Results

### Key Metrics

- **P50 FCT**: Median flow latency (typical case)
- **P95/P99 FCT**: Tail latency (SLA targets)
- **Avg FCT**: Mean latency over all packets
- **FCT classification**: Identify bottlenecks

### Custom Thresholds

```bash
# Classify flows as SHORT (<50ms), MEDIUM (<500ms), LONG (<5000ms)
python3 test-scripts/analyze_fct.py -i fct_data.csv \
  --short 50 --medium 500 --long 5000 --graph output.png
```

---

## 📁 Output Files

| File | Contains |
|------|----------|
| `fct_data.csv` | Raw FCT telemetry (all packets) |
| `fct_visual.png` | 4-panel matplotlib visualization |
| console text | Per-packet FCT in real-time |

---

## 💡 Next Steps

1. **Multiple flows**: Generate traffic from multiple hosts
   ```bash
   mininet> xterm h1 h2 h3
   # In each terminal, run iperf to different destination
   ```

2. **Correlation analysis**: Compare FCT with queue_depth
   - When queue grows, does FCT increase?
   - What's the latency impact?

3. **Load testing**: Test under various traffic loads
   - Light: 5-10 Mbps
   - Medium: 50-100 Mbps
   - Heavy: 500+ Mbps

4. **Flow type analysis**: Study impact of flow size
   - Mice (small flows): typically SHORT
   - Elephants (large flows): typically MEDIUM/LONG

---

## 🎓 Understanding FCT

### What FCT Measures

```
First Packet                 Last Packet
    |                             |
    v                             v
Flow Start Time ----FCT----> Flow End Time

FCT = sum of all per-packet latencies
    = reflects congestion + propagation delay
    = better than raw RTT (considers queuing)
```

### Why It Matters

- **Load Balancing**: HULA should reduce FCT via better path selection
- **Congestion**: High FCT = network overloaded
- **Predictability**: Low P99 FCT = predictable performance
- **SLA Compliance**: Monitor against targets

---

## 🚀 Full Example

```bash
# 1. Setup
cd ~/Pictures/Hula-hoop_small.bkp
export PYTHONPATH=$PYTHONPATH:$(pwd)/build

# 2. Build
make clean && make

# 3. Terminal 1: Controller
./controller.py

# 4. Terminal 2: Inside mininet h9
mininet> xterm h9
h9$ sudo python3 test-scripts/fct_receiver.py -o fct_data.csv

# 5. Terminal 3: Inside mininet h1
mininet> xterm h1
h1$ iperf -c 10.0.9.1 -b 50M -t 30

# 6. After iperf ends, analyze
python3 test-scripts/analyze_fct.py -i fct_data.csv --graph fct_out.png

# 7. View results
# Check fct_data.csv (raw data)
# Check fct_out.png (4-panel visualization)
```

---

**Ready to monitor FCT! 🎉**

Questions? See [FCT_TELEMETRY.md](FCT_TELEMETRY.md) for complete documentation.
