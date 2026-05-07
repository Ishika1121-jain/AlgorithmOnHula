#!/usr/bin/env python3
"""
HULA Queue Depth Analysis Tool

Analyzes queue_depth telemetry CSV files and provides:
- Statistical summary (min, max, avg, percentiles)
- Per-flow analysis
- Timeline visualization (text and graph)
- Congestion detection

Usage:
    python3 analyze_telemetry.py -i queue_depth_telemetry.csv [-o output_prefix]
"""

import sys
import csv
import argparse
from collections import defaultdict
from datetime import datetime
import statistics


def load_csv(filename):
    """Load telemetry data from CSV file."""
    data = []
    try:
        with open(filename, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row['timestamp_s'] = float(row['timestamp_s'])
                row['src_port'] = int(row['src_port'])
                row['dst_port'] = int(row['dst_port'])
                row['queue_depth_bytes'] = int(row['queue_depth_bytes'])
                data.append(row)
    except Exception as e:
        print(f"❌ Error loading CSV: {e}", file=sys.stderr)
        sys.exit(1)
    
    return data


def analyze_global_stats(data):
    """Compute global queue depth statistics."""
    if not data:
        print("⚠️ No data to analyze")
        return None
    
    queue_depths = [d['queue_depth_bytes'] for d in data]
    
    stats = {
        'count': len(queue_depths),
        'min': min(queue_depths),
        'max': max(queue_depths),
        'avg': statistics.mean(queue_depths),
        'median': statistics.median(queue_depths),
        'stdev': statistics.stdev(queue_depths) if len(queue_depths) > 1 else 0,
        'p95': sorted(queue_depths)[int(len(queue_depths) * 0.95)],
        'p99': sorted(queue_depths)[int(len(queue_depths) * 0.99)],
    }
    
    return stats


def analyze_per_flow(data):
    """Analyze queue depth per flow."""
    flow_stats = defaultdict(lambda: {'queue_depths': [], 'count': 0})
    
    for d in data:
        flow_id = f"{d['src_ip']}:{d['src_port']}->{d['dst_ip']}:{d['dst_port']}"
        flow_stats[flow_id]['queue_depths'].append(d['queue_depth_bytes'])
        flow_stats[flow_id]['count'] += 1
    
    # Compute per-flow statistics
    flow_summary = {}
    for flow_id, stats in flow_stats.items():
        queue_depths = stats['queue_depths']
        flow_summary[flow_id] = {
            'count': len(queue_depths),
            'min': min(queue_depths),
            'max': max(queue_depths),
            'avg': statistics.mean(queue_depths),
            'median': statistics.median(queue_depths),
        }
    
    return flow_summary


def detect_congestion(data, threshold=200):
    """Detect periods of high queue depth (congestion)."""
    congestion_periods = []
    current_period = None
    
    for d in data:
        if d['queue_depth_bytes'] >= threshold:
            if current_period is None:
                current_period = {
                    'start_time': d['timestamp_s'],
                    'start_idx': len(congestion_periods),
                    'peak': d['queue_depth_bytes']
                }
            else:
                current_period['peak'] = max(current_period['peak'], d['queue_depth_bytes'])
        else:
            if current_period is not None:
                current_period['end_time'] = d['timestamp_s']
                current_period['duration'] = current_period['end_time'] - current_period['start_time']
                congestion_periods.append(current_period)
                current_period = None
    
    return congestion_periods


def plot_text_graph(data, width=80, height=20):
    """Create a simple text-based graph of queue depth over time."""
    if not data:
        return ""
    
    # Normalize queue depth to height
    queue_depths = [d['queue_depth_bytes'] for d in data]
    max_depth = max(queue_depths) if queue_depths else 1
    min_depth = min(queue_depths)
    range_depth = max_depth - min_depth if max_depth > min_depth else 1
    
    # Sample data if too many points
    sample_interval = max(1, len(data) // width)
    sampled_data = data[::sample_interval]
    
    # Create graph
    graph = [[' ' for _ in range(width)] for _ in range(height)]
    
    for x, d in enumerate(sampled_data):
        if x >= width:
            break
        
        # Normalize queue depth to 0-height range
        normalized = (d['queue_depth_bytes'] - min_depth) / range_depth if range_depth > 0 else 0
        y = int(normalized * (height - 1))
        y = height - 1 - y  # Flip y axis (top is max)
        
        graph[y][x] = '█'
    
    # Add axis labels
    output = []
    output.append(f"Queue Depth Timeline (height={height}, width={width})")
    output.append(f"Max: {max_depth} bytes, Min: {min_depth} bytes, Range: {range_depth} bytes")
    output.append("-" * (width + 2))
    
    for row in graph:
        output.append("│" + "".join(row) + "│")
    
    output.append("-" * (width + 2))
    
    # Time axis
    if len(sampled_data) > 1:
        start_time = sampled_data[0]['timestamp_s']
        end_time = sampled_data[-1]['timestamp_s']
        output.append(f"Time: {start_time:.1f}s to {end_time:.1f}s (duration: {end_time - start_time:.1f}s)")
    
    return "\n".join(output)


def try_plot_matplotlib(data, output_file):
    """Try to create matplotlib visualization if available."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime as dt
        
        # Prepare data
        timestamps = [d['timestamp_s'] for d in data]
        queue_depths = [d['queue_depth_bytes'] for d in data]
        
        # Create figure
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))
        
        # Plot 1: Queue depth timeline
        ax1.plot(timestamps, queue_depths, marker='o', linestyle='-', markersize=2, linewidth=1)
        ax1.fill_between(timestamps, queue_depths, alpha=0.3)
        ax1.set_xlabel('Time (seconds)')
        ax1.set_ylabel('Queue Depth (bytes)')
        ax1.set_title('HULA Queue Depth Over Time')
        ax1.grid(True, alpha=0.3)
        
        # Plot 2: Histogram
        ax2.hist(queue_depths, bins=30, edgecolor='black', alpha=0.7)
        ax2.set_xlabel('Queue Depth (bytes)')
        ax2.set_ylabel('Frequency')
        ax2.set_title('Queue Depth Distribution')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(output_file, dpi=150)
        print(f"✅ Graph saved to: {output_file}")
        
    except ImportError:
        print("⚠️  matplotlib not installed. Install with: pip install matplotlib")
        return False
    except Exception as e:
        print(f"⚠️  Could not create matplotlib plot: {e}")
        return False
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Analyze HULA queue_depth telemetry data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze telemetry data
  python3 analyze_telemetry.py -i queue_depth_telemetry.csv

  # Generate graph image
  python3 analyze_telemetry.py -i queue_depth_telemetry.csv --graph output_graph.png

  # High congestion threshold
  python3 analyze_telemetry.py -i queue_depth_telemetry.csv --threshold 250
        """
    )
    parser.add_argument(
        '-i', '--input',
        type=str,
        required=True,
        help='Input telemetry CSV file'
    )
    parser.add_argument(
        '-o', '--output-prefix',
        type=str,
        default='telemetry_analysis',
        help='Output prefix for analysis files'
    )
    parser.add_argument(
        '--graph',
        type=str,
        help='Generate matplotlib graph (PNG file)'
    )
    parser.add_argument(
        '--threshold',
        type=int,
        default=200,
        help='Congestion threshold in bytes (default: 200)'
    )
    
    args = parser.parse_args()
    
    # Load data
    print(f"📂 Loading telemetry from: {args.input}")
    data = load_csv(args.input)
    print(f"✅ Loaded {len(data)} telemetry records\n")
    
    # Global statistics
    print("=" * 80)
    print("GLOBAL QUEUE DEPTH STATISTICS")
    print("=" * 80)
    
    global_stats = analyze_global_stats(data)
    if global_stats:
        print(f"  Total Samples:     {global_stats['count']}")
        print(f"  Min Queue Depth:   {global_stats['min']} bytes")
        print(f"  Max Queue Depth:   {global_stats['max']} bytes")
        print(f"  Avg Queue Depth:   {global_stats['avg']:.2f} bytes")
        print(f"  Median:            {global_stats['median']} bytes")
        print(f"  Std Dev:           {global_stats['stdev']:.2f} bytes")
        print(f"  95th Percentile:   {global_stats['p95']} bytes")
        print(f"  99th Percentile:   {global_stats['p99']} bytes")
    
    # Per-flow analysis
    print("\n" + "=" * 80)
    print("PER-FLOW QUEUE DEPTH STATISTICS")
    print("=" * 80)
    
    flow_stats = analyze_per_flow(data)
    sorted_flows = sorted(flow_stats.items(), key=lambda x: x[1]['avg'], reverse=True)
    
    print(f"\nTop 10 flows by average queue depth:")
    for i, (flow_id, stats) in enumerate(sorted_flows[:10], 1):
        print(f"\n  {i}. {flow_id}")
        print(f"     Samples: {stats['count']}")
        print(f"     Avg:     {stats['avg']:.2f} bytes")
        print(f"     Min/Max: {stats['min']}/{stats['max']} bytes")
    
    # Congestion detection
    print("\n" + "=" * 80)
    print("CONGESTION DETECTION")
    print("=" * 80)
    print(f"Threshold: {args.threshold} bytes\n")
    
    congestion_periods = detect_congestion(data, args.threshold)
    if congestion_periods:
        print(f"Found {len(congestion_periods)} congestion period(s):\n")
        for i, period in enumerate(congestion_periods, 1):
            print(f"  Period {i}:")
            print(f"    Time:     {period['start_time']:.2f}s - {period['end_time']:.2f}s")
            print(f"    Duration: {period['duration']:.2f}s")
            print(f"    Peak:     {period['peak']} bytes")
    else:
        print(f"✅ No congestion periods detected (threshold: {args.threshold} bytes)")
    
    # Text-based graph
    print("\n" + "=" * 80)
    print("QUEUE DEPTH TIMELINE (Text Graph)")
    print("=" * 80 + "\n")
    print(plot_text_graph(data, width=80, height=15))
    
    # Matplotlib graph
    if args.graph:
        print("\n" + "=" * 80)
        print("GENERATING GRAPH")
        print("=" * 80)
        try_plot_matplotlib(data, args.graph)
    else:
        print("\n💡 Tip: Use --graph output.png to generate a matplotlib visualization")
    
    print("\n✅ Analysis complete!")


if __name__ == '__main__':
    main()
