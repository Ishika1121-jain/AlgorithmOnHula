#!/usr/bin/env python3
"""
HULA Flow Completion Time (FCT) Analysis Tool

Analyzes FCT telemetry CSV files and provides:
- Statistical summary (min, max, avg, percentiles)
- Per-flow FCT analysis
- FCT value classification (short/medium/long flows)
- Timeline visualization
- Histogram and CDF plots

Usage:
    python3 analyze_fct.py -i fct_telemetry.csv [--graph output.png] [--threshold 100]
"""

import sys
import csv
import argparse
from collections import defaultdict
from datetime import datetime
import statistics


def load_csv(filename):
    """Load FCT telemetry data from CSV file."""
    data = []
    try:
        with open(filename, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row['timestamp_s'] = float(row['timestamp_s'])
                row['src_port'] = int(row['src_port'])
                row['dst_port'] = int(row['dst_port'])
                row['fct_ns'] = int(row['fct_ns'])
                row['fct_us'] = float(row['fct_us'])
                row['fct_ms'] = float(row['fct_ms'])
                row['queue_depth_bytes'] = int(row['queue_depth_bytes'])
                data.append(row)
    except Exception as e:
        print(f"❌ Error loading CSV: {e}", file=sys.stderr)
        sys.exit(1)
    
    return data


def analyze_global_fct_stats(data):
    """Compute global FCT statistics."""
    if not data:
        print("⚠️ No data to analyze")
        return None
    
    # Use FCT in milliseconds for analysis
    fct_values = [d['fct_ms'] for d in data]
    
    stats = {
        'count': len(fct_values),
        'min_ms': min(fct_values),
        'max_ms': max(fct_values),
        'avg_ms': statistics.mean(fct_values),
        'median_ms': statistics.median(fct_values),
        'stdev_ms': statistics.stdev(fct_values) if len(fct_values) > 1 else 0,
        'p50_ms': sorted(fct_values)[int(len(fct_values) * 0.50)],
        'p95_ms': sorted(fct_values)[int(len(fct_values) * 0.95)],
        'p99_ms': sorted(fct_values)[int(len(fct_values) * 0.99)],
    }
    
    return stats


def analyze_per_flow_fct(data):
    """Analyze FCT per flow."""
    flow_data = defaultdict(lambda: {'fct_values': [], 'count': 0})
    
    for d in data:
        flow_id = d['flow_id']
        flow_data[flow_id]['fct_values'].append(d['fct_ms'])
        flow_data[flow_id]['count'] += 1
    
    # Compute per-flow statistics
    flow_summary = {}
    for flow_id, stats in flow_data.items():
        fct_vals = stats['fct_values']
        flow_summary[flow_id] = {
            'count': len(fct_vals),
            'min_ms': min(fct_vals),
            'max_ms': max(fct_vals),
            'avg_ms': statistics.mean(fct_vals),
            'median_ms': statistics.median(fct_vals),
            'total_flow_time_ms': max(fct_vals),  # Total time from first to last packet
        }
    
    return flow_summary


def classify_fct(fct_ms, thresholds=None):
    """Classify FCT into categories."""
    if thresholds is None:
        thresholds = {'short': 10, 'medium': 100, 'long': 1000}
    
    if fct_ms <= thresholds['short']:
        return 'SHORT'
    elif fct_ms <= thresholds['medium']:
        return 'MEDIUM'
    elif fct_ms <= thresholds['long']:
        return 'LONG'
    else:
        return 'VERY_LONG'


def analyze_fct_distribution(data):
    """Analyze FCT distribution by category."""
    categories = defaultdict(int)
    
    for d in data:
        category = classify_fct(d['fct_ms'])
        categories[category] += 1
    
    return categories


def plot_text_fct_graph(data, width=80, height=20):
    """Create a simple text-based graph of FCT over time."""
    if not data:
        return ""
    
    # Normalize FCT to height
    fct_values = [d['fct_ms'] for d in data]
    max_fct = max(fct_values) if fct_values else 1
    min_fct = min(fct_values)
    range_fct = max_fct - min_fct if max_fct > min_fct else 1
    
    # Sample data if too many points
    sample_interval = max(1, len(data) // width)
    sampled_data = data[::sample_interval]
    
    # Create graph
    graph = [[' ' for _ in range(width)] for _ in range(height)]
    
    for x, d in enumerate(sampled_data):
        if x >= width:
            break
        
        # Normalize FCT to 0-height range
        normalized = (d['fct_ms'] - min_fct) / range_fct if range_fct > 0 else 0
        y = int(normalized * (height - 1))
        y = height - 1 - y  # Flip y axis (top is max)
        
        graph[y][x] = '█'
    
    # Add axis labels
    output = []
    output.append(f"FCT Timeline (height={height}, width={width})")
    output.append(f"Max: {max_fct:.3f}ms, Min: {min_fct:.3f}ms, Range: {range_fct:.3f}ms")
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
        import numpy as np
        
        # Prepare data
        timestamps = [d['timestamp_s'] for d in data]
        fct_ms = [d['fct_ms'] for d in data]
        queue_depth = [d['queue_depth_bytes'] for d in data]
        
        # Create figure with subplots
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        # Plot 1: FCT timeline
        ax = axes[0, 0]
        ax.plot(timestamps, fct_ms, marker='o', linestyle='-', markersize=2, linewidth=1, color='steelblue')
        ax.fill_between(timestamps, fct_ms, alpha=0.3, color='steelblue')
        ax.set_xlabel('Time (seconds)')
        ax.set_ylabel('FCT (milliseconds)')
        ax.set_title('Flow Completion Time Over Time')
        ax.grid(True, alpha=0.3)
        
        # Plot 2: FCT histogram
        ax = axes[0, 1]
        ax.hist(fct_ms, bins=30, edgecolor='black', alpha=0.7, color='coral')
        avg_fct = np.mean(fct_ms)
        ax.axvline(avg_fct, color='red', linestyle='--', linewidth=2, label=f'Mean: {avg_fct:.2f}ms')
        ax.set_xlabel('FCT (milliseconds)')
        ax.set_ylabel('Frequency')
        ax.set_title('FCT Distribution')
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        
        # Plot 3: FCT vs Queue Depth
        ax = axes[1, 0]
        ax.scatter(queue_depth, fct_ms, alpha=0.5, s=20, color='green')
        ax.set_xlabel('Queue Depth (bytes)')
        ax.set_ylabel('FCT (milliseconds)')
        ax.set_title('FCT vs Queue Depth Correlation')
        ax.grid(True, alpha=0.3)
        
        # Plot 4: CDF (Cumulative Distribution Function)
        ax = axes[1, 1]
        sorted_fct = np.sort(fct_ms)
        y = np.arange(1, len(sorted_fct) + 1) / len(sorted_fct)
        ax.plot(sorted_fct, y, linewidth=2, color='darkblue')
        
        # Mark percentiles
        p95 = sorted_fct[int(len(sorted_fct) * 0.95)]
        p99 = sorted_fct[int(len(sorted_fct) * 0.99)]
        ax.axvline(p95, color='orange', linestyle='--', linewidth=2, label=f'P95: {p95:.2f}ms')
        ax.axvline(p99, color='red', linestyle='--', linewidth=2, label=f'P99: {p99:.2f}ms')
        
        ax.set_xlabel('FCT (milliseconds)')
        ax.set_ylabel('Cumulative Probability')
        ax.set_title('Cumulative Distribution Function (CDF)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
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
        description="Analyze HULA FCT telemetry data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze FCT data
  python3 analyze_fct.py -i fct_telemetry.csv

  # Generate graph
  python3 analyze_fct.py -i fct_telemetry.csv --graph fct_visual.png

  # Custom classification thresholds
  python3 analyze_fct.py -i fct_telemetry.csv --short 5 --medium 50 --long 500
        """
    )
    parser.add_argument(
        '-i', '--input',
        type=str,
        required=True,
        help='Input FCT telemetry CSV file'
    )
    parser.add_argument(
        '--graph',
        type=str,
        help='Generate matplotlib graph (PNG file)'
    )
    parser.add_argument(
        '--short',
        type=float,
        default=10,
        help='Short flow threshold (ms), default: 10'
    )
    parser.add_argument(
        '--medium',
        type=float,
        default=100,
        help='Medium flow threshold (ms), default: 100'
    )
    parser.add_argument(
        '--long',
        type=float,
        default=1000,
        help='Long flow threshold (ms), default: 1000'
    )
    
    args = parser.parse_args()
    
    # Load data
    print(f"📂 Loading FCT telemetry from: {args.input}")
    data = load_csv(args.input)
    print(f"✅ Loaded {len(data)} FCT records\n")
    
    # Global statistics
    print("=" * 90)
    print("GLOBAL FLOW COMPLETION TIME (FCT) STATISTICS")
    print("=" * 90)
    
    global_stats = analyze_global_fct_stats(data)
    if global_stats:
        print(f"  Total Samples:         {global_stats['count']}")
        print(f"  Min FCT:               {global_stats['min_ms']:.6f} ms")
        print(f"  Max FCT:               {global_stats['max_ms']:.6f} ms")
        print(f"  Avg FCT:               {global_stats['avg_ms']:.6f} ms")
        print(f"  Median FCT:            {global_stats['median_ms']:.6f} ms")
        print(f"  Std Dev:               {global_stats['stdev_ms']:.6f} ms")
        print(f"  50th Percentile (P50): {global_stats['p50_ms']:.6f} ms")
        print(f"  95th Percentile (P95): {global_stats['p95_ms']:.6f} ms")
        print(f"  99th Percentile (P99): {global_stats['p99_ms']:.6f} ms")
    
    # FCT Distribution
    print("\n" + "=" * 90)
    print("FLOW CLASSIFICATION BY FCT")
    print("=" * 90)
    print(f"  SHORT (<{args.short}ms) | MEDIUM (<{args.medium}ms) | LONG (<{args.long}ms) | VERY_LONG (>{args.long}ms)\n")
    
    thresholds = {'short': args.short, 'medium': args.medium, 'long': args.long}
    distribution = analyze_fct_distribution(data)
    
    for category in ['SHORT', 'MEDIUM', 'LONG', 'VERY_LONG']:
        count = distribution.get(category, 0)
        percentage = (count / len(data)) * 100
        bar = '█' * int(percentage / 2)
        print(f"  {category:10s}: {count:5d} ({percentage:5.1f}%) {bar}")
    
    # Per-flow analysis
    print("\n" + "=" * 90)
    print("PER-FLOW FCT ANALYSIS")
    print("=" * 90)
    
    flow_stats = analyze_per_flow_fct(data)
    sorted_flows = sorted(flow_stats.items(), key=lambda x: x[1]['avg_ms'], reverse=True)
    
    print(f"\nTop 10 flows by average FCT:")
    for i, (flow_id, stats) in enumerate(sorted_flows[:10], 1):
        print(f"\n  {i}. {flow_id}")
        print(f"     Packets:  {stats['count']}")
        print(f"     Avg FCT:  {stats['avg_ms']:.6f} ms")
        print(f"     Min/Max:  {stats['min_ms']:.6f} / {stats['max_ms']:.6f} ms")
        print(f"     Total:    {stats['total_flow_time_ms']:.6f} ms")
    
    # Text-based graph
    print("\n" + "=" * 90)
    print("FCT TIMELINE (Text Graph)")
    print("=" * 90 + "\n")
    print(plot_text_fct_graph(data, width=80, height=15))
    
    # Matplotlib graph
    if args.graph:
        print("\n" + "=" * 90)
        print("GENERATING VISUALIZATION")
        print("=" * 90)
        try_plot_matplotlib(data, args.graph)
    else:
        print("\n💡 Tip: Use --graph output.png to generate a matplotlib visualization")
    
    print("\n✅ FCT analysis complete!")


if __name__ == '__main__':
    main()
