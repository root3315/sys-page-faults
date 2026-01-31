#!/usr/bin/env python3
"""
sys-page-faults: Monitor and analyze system page faults for performance
profiling and debugging.

Reads page fault data from /proc filesystem and provides real-time
monitoring, historical analysis, and bottleneck identification.
"""

import argparse
import os
import signal
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


PROC_PATH = Path("/proc")
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")


@dataclass
class PageFaultStats:
    """Holds page fault statistics for a process or system."""
    pid: int = 0
    name: str = ""
    minor_faults: int = 0
    major_faults: int = 0
    children_minor_faults: int = 0
    children_major_faults: int = 0
    rss_pages: int = 0
    timestamp: float = 0.0
    history: list = field(default_factory=list)


@dataclass
class SystemVmStats:
    """System-wide VM statistics from /proc/vmstat."""
    pgfault: int = 0
    pgmajfault: int = 0
    pgscan_kswapd: int = 0
    pgscan_direct: int = 0
    pgsteal_kswapd: int = 0
    pgsteal_direct: int = 0
    pgactivate: int = 0
    pgdeactivate: int = 0
    pginodesteal: int = 0
    allocstall: int = 0


def read_proc_stat(pid: int) -> Optional[PageFaultStats]:
    """
    Read page fault statistics for a specific PID from /proc/[pid]/stat.
    Fields 12 and 14 contain minor and major fault counts respectively.
    """
    stat_file = PROC_PATH / str(pid) / "stat"
    try:
        content = stat_file.read_text().strip()
        parts = content.split(")")
        if len(parts) < 2:
            return None
        name = parts[0].split("(")[1]
        fields = parts[2].split()
        if len(fields) < 22:
            return None
        stats = PageFaultStats(
            pid=pid,
            name=name,
            minor_faults=int(fields[9]),
            major_faults=int(fields[11]),
            children_minor_faults=int(fields[13]),
            children_major_faults=int(fields[14]),
            rss_pages=int(fields[21]),
            timestamp=time.time(),
        )
        return stats
    except (FileNotFoundError, PermissionError, ProcessLookupError,
            IndexError, ValueError):
        return None


def read_proc_smaps(pid: int) -> dict:
    """
    Read /proc/[pid]/smaps_rollup to get memory mapping details.
    Returns dict with memory region statistics.
    """
    smaps_file = PROC_PATH / str(pid) / "smaps_rollup"
    result = {
        "rss": 0,
        "pss": 0,
        "shared_clean": 0,
        "shared_dirty": 0,
        "private_clean": 0,
        "private_dirty": 0,
        "referenced": 0,
        "anonymous": 0,
        "swap": 0,
    }
    try:
        content = smaps_file.read_text()
        for line in content.splitlines():
            line = line.strip()
            for key in result:
                if line.startswith(f"{key}:"):
                    value_str = line.split(":")[1].strip().split()[0]
                    try:
                        result[key] = int(value_str)
                    except ValueError:
                        pass
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        pass
    return result


def read_system_vmstat() -> SystemVmStats:
    """
    Read system-wide VM statistics from /proc/vmstat.
    Provides global page fault counters and memory pressure indicators.
    """
    vm_stats = SystemVmStats()
    vmstat_file = PROC_PATH / "vmstat"
    try:
        content = vmstat_file.read_text()
        for line in content.splitlines():
            parts = line.split()
            if len(parts) != 2:
                continue
            key, value = parts
            try:
                val = int(value)
            except ValueError:
                continue
            if key == "pgfault":
                vm_stats.pgfault = val
            elif key == "pgmajfault":
                vm_stats.pgmajfault = val
            elif key == "pgscan_kswapd":
                vm_stats.pgscan_kswapd = val
            elif key == "pgscan_direct":
                vm_stats.pgscan_direct = val
            elif key == "pgsteal_kswapd":
                vm_stats.pgsteal_kswapd = val
            elif key == "pgsteal_direct":
                vm_stats.pgsteal_direct = val
            elif key == "pgactivate":
                vm_stats.pgactivate = val
            elif key == "pgdeactivate":
                vm_stats.pgdeactivate = val
            elif key == "pginodesteal":
                vm_stats.pginodesteal = val
            elif key == "allocstall":
                vm_stats.allocstall = val
    except (FileNotFoundError, PermissionError):
        pass
    return vm_stats


def find_process_by_name(name_pattern: str) -> list:
    """
    Find all running processes matching a name pattern.
    Searches /proc/[pid]/comm for each running process.
    """
    matches = []
    for proc_dir in PROC_PATH.iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            comm_file = proc_dir / "comm"
            comm = comm_file.read_text().strip()
            if name_pattern.lower() in comm.lower():
                matches.append(int(proc_dir.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return matches


def calculate_fault_rates(current: PageFaultStats, previous: PageFaultStats) -> dict:
    """
    Calculate page fault rates per second between two sampling points.
    Returns dict with minor and major fault rates.
    """
    time_delta = current.timestamp - previous.timestamp
    if time_delta <= 0:
        return {"minor_rate": 0.0, "major_rate": 0.0}
    minor_delta = current.minor_faults - previous.minor_faults
    major_delta = current.major_faults - previous.major_faults
    return {
        "minor_rate": minor_delta / time_delta,
        "major_rate": major_delta / time_delta,
    }


def format_bytes(pages: int) -> str:
    """Convert page count to human-readable byte string."""
    total_bytes = pages * PAGE_SIZE
    if total_bytes < 1024:
        return f"{total_bytes} B"
    elif total_bytes < 1024 * 1024:
        return f"{total_bytes / 1024:.2f} KB"
    elif total_bytes < 1024 * 1024 * 1024:
        return f"{total_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{total_bytes / (1024 * 1024 * 1024):.2f} GB"


def print_process_report(stats: PageFaultStats, rates: Optional[dict] = None):
    """Print formatted page fault report for a single process."""
    print(f"  PID:            {stats.pid}")
    print(f"  Name:           {stats.name}")
    print(f"  Minor Faults:   {stats.minor_faults:,}")
    print(f"  Major Faults:   {stats.major_faults:,}")
    print(f"  RSS:            {format_bytes(stats.rss_pages)}")
    if stats.children_minor_faults or stats.children_major_faults:
        print(f"  Children Minor: {stats.children_minor_faults:,}")
        print(f"  Children Major: {stats.children_major_faults:,}")
    if rates:
        print(f"  Minor Rate:     {rates['minor_rate']:.2f} faults/sec")
        print(f"  Major Rate:     {rates['major_rate']:.2f} faults/sec")
    print()


def print_system_report(vm_stats: SystemVmStats):
    """Print formatted system-wide VM statistics report."""
    print("=" * 60)
    print("System-Wide VM Statistics (/proc/vmstat)")
    print("=" * 60)
    print(f"  Total Page Faults:      {vm_stats.pgfault:,}")
    print(f"  Total Major Faults:     {vm_stats.pgmajfault:,}")
    print(f"  Page Scan (kswapd):     {vm_stats.pgscan_kswapd:,}")
    print(f"  Page Scan (direct):     {vm_stats.pgscan_direct:,}")
    print(f"  Page Steal (kswapd):    {vm_stats.pgsteal_kswapd:,}")
    print(f"  Page Steal (direct):    {vm_stats.pgsteal_direct:,}")
    print(f"  Pages Activated:        {vm_stats.pgactivate:,}")
    print(f"  Pages Deactivated:      {vm_stats.pgdeactivate:,}")
    print(f"  Inode Steal:            {vm_stats.pginodesteal:,}")
    print(f"  Allocation Stalls:      {vm_stats.allocstall:,}")
    print()
    fault_ratio = 0.0
    if vm_stats.pgfault > 0:
        fault_ratio = (vm_stats.pgmajfault / vm_stats.pgfault) * 100
    print(f"  Major/Minor Fault Ratio: {fault_ratio:.4f}%")
    print()


def analyze_memory_pressure(vm_stats: SystemVmStats) -> list:
    """
    Analyze system memory pressure based on VM statistics.
    Returns list of diagnostic messages about potential issues.
    """
    findings = []
    if vm_stats.allocstall > 0:
        findings.append(
            f"WARNING: {vm_stats.allocstall} memory allocation stalls detected. "
            "System may be under memory pressure."
        )
    if vm_stats.pgscan_direct > 10000:
        findings.append(
            f"HIGH direct page scanning ({vm_stats.pgscan_direct:,}). "
            "Consider increasing available memory."
        )
    if vm_stats.pgmajfault > vm_stats.pgfault * 0.1 and vm_stats.pgfault > 0:
        findings.append(
            "High ratio of major page faults (>10%). "
            "Processes may be experiencing significant I/O wait."
        )
    if vm_stats.pginodesteal > 5000:
        findings.append(
            f"Significant inode stealing ({vm_stats.pginodesteal:,}). "
            "File system metadata memory may be constrained."
        )
    total_scanned = vm_stats.pgscan_kswapd + vm_stats.pgscan_direct
    total_stolen = vm_stats.pgsteal_kswapd + vm_stats.pgsteal_direct
    if total_scanned > 0:
        steal_efficiency = (total_stolen / total_scanned) * 100
        if steal_efficiency < 50:
            findings.append(
                f"Low page reclaim efficiency ({steal_efficiency:.1f}%). "
                "Memory reclaim is struggling to free pages."
            )
    return findings


def monitor_process(pid: int, interval: float, count: int):
    """Continuously monitor a process and report page fault rates."""
    previous = read_proc_stat(pid)
    if previous is None:
        print(f"Error: Cannot read stats for PID {pid}")
        sys.exit(1)
    print(f"Monitoring PID {pid} ({previous.name}) every {interval}s...")
    print("Press Ctrl+C to stop.\n")
    iteration = 0
    while count == 0 or iteration < count:
        time.sleep(interval)
        current = read_proc_stat(pid)
        if current is None:
            print(f"Process {pid} has terminated.")
            break
        rates = calculate_fault_rates(current, previous)
        print(f"[{time.strftime('%H:%M:%S')}] ", end="")
        print(f"Minor: {rates['minor_rate']:.2f}/s  "
              f"Major: {rates['major_rate']:.2f}/s  "
              f"RSS: {format_bytes(current.rss_pages)}")
        previous = current
        iteration += 1


def monitor_system(interval: float, count: int):
    """Continuously monitor system-wide page faults."""
    previous = read_system_vmstat()
    print(f"Monitoring system page faults every {interval}s...")
    print("Press Ctrl+C to stop.\n")
    iteration = 0
    while count == 0 or iteration < count:
        time.sleep(interval)
        current = read_system_vmstat()
        time_delta = interval
        minor_rate = (current.pgfault - previous.pgfault) / time_delta
        major_rate = (current.pgmajfault - previous.pgmajfault) / time_delta
        print(f"[{time.strftime('%H:%M:%S')}] ", end="")
        print(f"Faults: {minor_rate:.2f}/s  "
              f"Major: {major_rate:.2f}/s  "
              f"Scan: {current.pgscan_kswapd + current.pgscan_direct - previous.pgscan_kswapd - previous.pgscan_direct:.0f}")
        previous = current
        iteration += 1


def find_top_fault_processes(top_n: int = 10) -> list:
    """Find the top N processes by total page fault count."""
    processes = []
    for proc_dir in PROC_PATH.iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            pid = int(proc_dir.name)
            stats = read_proc_stat(pid)
            if stats and stats.minor_faults + stats.major_faults > 0:
                processes.append(stats)
        except (ValueError, ProcessLookupError):
            continue
    processes.sort(key=lambda s: s.minor_faults + s.major_faults, reverse=True)
    return processes[:top_n]


def cmd_snapshot(args):
    """Take a snapshot of page fault statistics."""
    if args.system:
        vm_stats = read_system_vmstat()
        print_system_report(vm_stats)
        findings = analyze_memory_pressure(vm_stats)
        if findings:
            print("Memory Pressure Analysis:")
            for finding in findings:
                print(f"  - {finding}")
            print()
    if args.pid:
        stats = read_proc_stat(args.pid)
        if stats:
            print(f"Process Page Fault Snapshot (PID {args.pid}):")
            print("-" * 40)
            print_process_report(stats)
            smaps = read_proc_smaps(args.pid)
            if smaps["rss"] > 0:
                print("  Memory Breakdown (from smaps):")
                print(f"    PSS:            {format_bytes(smaps['pss'])}")
                print(f"    Shared Clean:   {format_bytes(smaps['shared_clean'])}")
                print(f"    Shared Dirty:   {format_bytes(smaps['shared_dirty'])}")
                print(f"    Private Clean:  {format_bytes(smaps['private_clean'])}")
                print(f"    Private Dirty:  {format_bytes(smaps['private_dirty'])}")
                print(f"    Anonymous:      {format_bytes(smaps['anonymous'])}")
                if smaps['swap'] > 0:
                    print(f"    Swap:           {format_bytes(smaps['swap'])}")
                print()
        else:
            print(f"Error: Cannot read stats for PID {args.pid}")
            sys.exit(1)
    if args.name:
        pids = find_process_by_name(args.name)
        if not pids:
            print(f"No processes found matching '{args.name}'")
            return
        print(f"Processes matching '{args.name}':")
        print("-" * 40)
        for pid in pids:
            stats = read_proc_stat(pid)
            if stats:
                print_process_report(stats)
    if args.top:
        print(f"Top {args.top} Processes by Page Faults:")
        print("-" * 40)
        top_procs = find_top_fault_processes(args.top)
        for stats in top_procs:
            print_process_report(stats)


def cmd_monitor(args):
    """Start continuous monitoring mode."""
    if args.pid:
        monitor_process(args.pid, args.interval, args.count)
    elif args.system or True:
        monitor_system(args.interval, args.count)


def cmd_analyze(args):
    """Analyze page fault patterns and provide recommendations."""
    vm_stats = read_system_vmstat()
    print("Page Fault Analysis Report")
    print("=" * 60)
    print()
    fault_ratio = 0.0
    if vm_stats.pgfault > 0:
        fault_ratio = (vm_stats.pgmajfault / vm_stats.pgfault) * 100
    print(f"Total Page Faults:    {vm_stats.pgfault:,}")
    print(f"Major Page Faults:    {vm_stats.pgmajfault:,}")
    print(f"Major Fault Ratio:    {fault_ratio:.4f}%")
    print()
    if fault_ratio > 5.0:
        print("STATUS: HIGH major fault ratio detected")
        print("Major faults cause disk I/O and significantly impact performance.")
        print()
        print("Recommendations:")
        print("  1. Increase system RAM to reduce page-ins from disk")
        print("  2. Use mlock() for critical memory regions")
        print("  3. Review memory-mapped file usage")
        print("  4. Consider using huge pages (madvise with MADV_HUGEPAGE)")
    elif fault_ratio > 1.0:
        print("STATUS: MODERATE major fault ratio")
        print("Some disk-backed page faults are occurring.")
        print()
        print("Recommendations:")
        print("  1. Monitor trending - increasing ratio may indicate memory pressure")
        print("  2. Check for memory leaks in long-running processes")
        print("  3. Consider pre-faulting memory with memset after allocation")
    else:
        print("STATUS: HEALTHY - Low major fault ratio")
        print("Most page faults are minor (handled without disk I/O).")
    print()
    findings = analyze_memory_pressure(vm_stats)
    if findings:
        print("Memory Pressure Findings:")
        for f in findings:
            print(f"  {f}")
        print()
    print("Top Fault-Generating Processes:")
    top_procs = find_top_fault_processes(5)
    for stats in top_procs:
        total_faults = stats.minor_faults + stats.major_faults
        pct = 0.0
        if vm_stats.pgfault > 0:
            pct = (total_faults / vm_stats.pgfault) * 100
        print(f"  PID {stats.pid:>6} ({stats.name:<15}): "
              f"{total_faults:>12,} faults ({pct:.2f}%)")


def main():
    parser = argparse.ArgumentParser(
        description="Monitor and analyze system page faults",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s snapshot --system              System-wide page fault snapshot
  %(prog)s snapshot --pid 1234            Snapshot for specific PID
  %(prog)s snapshot --name nginx          Snapshot for process name
  %(prog)s snapshot --top 20              Top 20 processes by faults
  %(prog)s monitor --interval 2           Monitor system continuously
  %(prog)s monitor --pid 1234 --interval 1 Monitor specific PID
  %(prog)s analyze                        Full analysis with recommendations
""",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    snapshot_parser = subparsers.add_parser("snapshot", help="Take a page fault snapshot")
    snapshot_parser.add_argument("--system", action="store_true", help="Include system-wide stats")
    snapshot_parser.add_argument("--pid", type=int, help="Process ID to snapshot")
    snapshot_parser.add_argument("--name", type=str, help="Process name to match")
    snapshot_parser.add_argument("--top", type=int, nargs="?", const=10, default=0,
                                 help="Show top N processes by faults")
    snapshot_parser.set_defaults(func=cmd_snapshot)

    monitor_parser = subparsers.add_parser("monitor", help="Continuous monitoring")
    monitor_parser.add_argument("--pid", type=int, help="Process ID to monitor")
    monitor_parser.add_argument("--interval", type=float, default=2.0,
                                help="Sampling interval in seconds")
    monitor_parser.add_argument("--count", type=int, default=0,
                                help="Number of samples (0 = infinite)")
    monitor_parser.add_argument("--system", action="store_true",
                                help="Monitor system-wide (default)")
    monitor_parser.set_defaults(func=cmd_monitor)

    analyze_parser = subparsers.add_parser("analyze", help="Analyze page fault patterns")
    analyze_parser.set_defaults(func=cmd_analyze)

    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
