# sys-page-faults

Monitor and analyze system page faults for performance profiling and debugging.

## Overview

This tool reads page fault data directly from the Linux `/proc` filesystem to provide real-time monitoring, historical analysis, and memory pressure diagnostics. It helps identify processes causing excessive paging and system-wide memory issues.

## Requirements

- Linux operating system (uses `/proc` filesystem)
- Python 3.7 or higher
- No external dependencies

## Installation

No installation required. Clone the repository and run directly:

```bash
git clone https://github.com/example/sys-page-faults.git
cd sys-page-faults
```

## Usage

### Snapshot Mode

Take a one-time snapshot of page fault statistics:

```bash
# System-wide page fault snapshot
python3 sys_page_faults.py snapshot --system

# Snapshot for a specific process
python3 sys_page_faults.py snapshot --pid 1234

# Find processes by name
python3 sys_page_faults.py snapshot --name nginx

# Top 10 processes by page fault count
python3 sys_page_faults.py snapshot --top 10

# Top 20 processes
python3 sys_page_faults.py snapshot --top 20
```

### Monitor Mode

Continuously monitor page fault rates:

```bash
# Monitor system-wide page faults every 2 seconds
python3 sys_page_faults.py monitor --interval 2

# Monitor a specific PID every second
python3 sys_page_faults.py monitor --pid 1234 --interval 1

# Take 10 samples then exit
python3 sys_page_faults.py monitor --interval 1 --count 10
```

### Analyze Mode

Full analysis with performance recommendations:

```bash
# Generate analysis report with recommendations
python3 sys_page_faults.py analyze
```

## Output Fields

### Process Statistics

| Field | Description |
|---|---|
| Minor Faults | Page faults handled without disk I/O (pages already in memory) |
| Major Faults | Page faults that required reading from disk (significant performance impact) |
| RSS | Resident Set Size - physical memory currently used |
| Minor Rate | Minor faults per second during monitoring |
| Major Rate | Major faults per second during monitoring |

### System-Wide Statistics

| Field | Description |
|---|---|
| pgfault | Total page faults across all processes |
| pgmajfault | Total major page faults |
| pgscan_kswapd | Pages scanned by kernel swap daemon |
| pgscan_direct | Pages scanned by direct reclaim |
| pgsteal_kswapd | Pages reclaimed by kswapd |
| pgsteal_direct | Pages reclaimed by direct reclaim |
| allocstall | Memory allocation stalls (indicator of pressure) |

## Page Fault Types

- **Minor (soft) fault**: The requested page is in memory but not mapped in the process page tables. Resolved quickly without disk I/O.

- **Major (hard) fault**: The requested page must be loaded from disk. Causes significant latency and should be minimized for performance-critical applications.

## Memory Pressure Analysis

The `analyze` command evaluates several indicators:

- **Major fault ratio**: Percentage of faults that are major. Above 5% indicates serious memory pressure.
- **Allocation stalls**: Count of times processes waited for memory allocation. Any value > 0 indicates pressure.
- **Page reclaim efficiency**: Ratio of pages successfully reclaimed vs scanned. Below 50% suggests inefficient memory reclaim.
- **Direct page scanning**: High values indicate the kernel is struggling to free memory.

## Performance Tips

1. **Reduce major faults**: Add more RAM or reduce working set size
2. **Pre-fault memory**: Call `memset` after large allocations to fault pages proactively
3. **Use huge pages**: `madvise(MADV_HUGEPAGE)` can reduce TLB pressure for large allocations
4. **Lock critical memory**: `mlock()` prevents paging for latency-sensitive regions
5. **Review mmap usage**: Memory-mapped files can cause major faults on access

## License

MIT License
