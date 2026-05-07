# HULA: Scalable Load Balancing Using Programmable Data Planes

Implementation and experimentation of the **HULA (Hop-by-hop Utilization-aware Load Balancing Architecture)** algorithm using **P4 programmable data planes**, Mininet, BMv2, and Python-based telemetry tools.  
This project is based on the original HULA research paper and includes modifications, telemetry collection, probe analysis, congestion monitoring, and comparative evaluation with reduced probe overhead.

---

# Project Overview

HULA is a scalable congestion-aware load balancing mechanism for data center networks.  
Unlike ECMP and traditional source-routing approaches, HULA dynamically selects the best next hop based on real-time link utilization using programmable switches.

This project includes:

- P4-based programmable switch pipeline
- Dynamic probe generation and forwarding
- Queue depth monitoring
- Flow Completion Time (FCT) analysis
- Fat-tree topology generation
- Probe overhead reduction mechanism
- Comparative evaluation graphs
- Telemetry collection using BMv2 + Mininet

The implementation and design are inspired by the original HULA paper. :contentReference[oaicite:0]{index=0}

---

# Repository Structure

```bash
Hula-hoop/
│
├── build/
├── topology-generation/
├── utils/
├── test-scripts/
├── controller.py
├── controller.bk.py
├── benchmark.py
├── README.md
└── topology.json
```

---

# Features

- Congestion-aware load balancing
- Probe-based adaptive routing
- Reduced probe overhead
- Queue depth telemetry monitoring
- Flow Completion Time (FCT) monitoring
- Fat-tree topology support
- P4Runtime controller integration
- BMv2 software switch support
- Mininet emulation support

---

# Requirements

## Software Dependencies

- Ubuntu 20.04+
- Python 3
- P4 Compiler (`p4c`)
- BMv2
- Mininet
- gRPC tools
- Wireshark
- Jupyter Notebook

---

# Compile gRPC Build Files

Run the following command from the project root:

```bash
python3 -m grpc_tools.protoc \
  --proto_path=utils/p4runtime_lib/proto \
  --python_out=build \
  --grpc_python_out=build \
  utils/p4runtime_lib/proto/p4/v1/p4runtime.proto \
  utils/p4runtime_lib/proto/p4/config/v1/p4info.proto \
  utils/p4runtime_lib/proto/p4/config/v1/p4types.proto \
  utils/p4runtime_lib/proto/p4/v1/p4data.proto \
  utils/p4runtime_lib/proto/google/rpc/status.proto
```

---

# Generate Topology

Run the Fat-tree topology generator:

```bash
cd topology-generation
python3 fattree.py
```

This generates the required `topology.json`.

---

# Build the Project

Run:

```bash
make
```

---

# Run the Controller

```bash
cd ~/Desktop/Hula-hoop

export PYTHONPATH=$PYTHONPATH:$(pwd)/build

python3 controller.py
```

Alternative command:

```bash
python3 ./controller.py \
  --p4info build/switch.p4info \
  --bmv2-json build/switch.json \
  --topo topology.json
```

---

# Running Probe Scripts

Run probe generation directly on a Mininet host:

```bash
h1 python3 test-scripts/probe.py &
```

---

# Generate Network Load

Start server:

```bash
iperf3 -s
```

Generate UDP traffic:

```bash
iperf -c 10.0.104.10 -u -b 10M -t 60
```

---

# Telemetry Monitoring

## Monitor Queue Depth

```bash
sudo python3 test-scripts/telemetry_receiver.py -o telemetry.csv
```

This stores queue depth telemetry in:

```bash
telemetry.csv
```

---

## Monitor Flow Completion Time (FCT)

```bash
sudo python3 test-scripts/fct_receiver.py -o fct.csv
```

This stores FCT data in:

```bash
fct.csv
```

---

# Wireshark / Packet Capture

Capture traffic between controller and switches:

```bash
sudo tcpdump -i s100-eth1 -w /tmp/s100-eth1.pcap
```

Open capture file:

```bash
wireshark /tmp/s100-eth1.pcap
```

Remove old capture:

```bash
sudo rm /tmp/s100-eth1.pcap
```

---

# Jupyter Notebook Support

To open Jupyter Notebook:

```bash
export PATH=$HOME/.local/bin:$PATH

jupyter notebook
```

---

# Experimental Results

The project evaluates:

- Probe rate reduction
- Control overhead reduction
- Queue depth variations
- Congestion handling
- FCT improvements

Comparison graphs were generated using telemetry data and plotted using Python + Matplotlib. :contentReference[oaicite:1]{index=1}

---

# Included Images

## Probe Comparison Graph

```markdown
![Probe Comparison](hula_fct_comparison.png)
```

![Probe Comparison](hula_fct_comparison.png)

---

## Probe Metrics Graph

```markdown
![Probe Metrics](hula_probe_metrics.png)
```

![Probe Metrics](hula_probe_metrics.png)

---

## Topology Diagram

```markdown
![Topology](topo.png)
```

![Topology](topo.png)

---

# Research Reference

This implementation is based on:

**HULA: Scalable Load Balancing Using Programmable Data Planes**  
Naga Katta, Mukesh Hira, Changhoon Kim, Anirudh Sivaraman, Jennifer Rexford :contentReference[oaicite:2]{index=2}

---

# Key Observations

- Modified HULA significantly reduces probe overhead.
- Queue congestion is minimized using adaptive probe rates.
- Lower control overhead compared to traditional HULA.
- Better scalability for large fat-tree topologies.

---

# Future Improvements

- Hardware switch deployment
- INT (In-band Network Telemetry) integration
- Machine learning based congestion prediction
- Dynamic adaptive probing frequency
- Multi-controller support

---

# Author

**Ishika Jain**

Project focused on programmable data plane research, congestion-aware routing, and scalable data center load balancing using P4.

---
