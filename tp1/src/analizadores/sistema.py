"""Analizador de Sistema Global."""

import os

from src.procfs import (
    parse_stat,
    parse_status,
    read_text,
    read_loadavg,
    read_meminfo,
)


def build_system_snapshot(pids):
    """Construye snapshot del sistema global."""
    memory = read_meminfo()
    loadavg = read_loadavg()
    uptime = read_text("/proc/uptime").split()
    uptime_seconds = float(uptime[0]) if uptime else 0.0
    
    proc_counts = {}
    total_threads = 0
    zombies = 0
    top_cpu = []
    top_rss = []
    
    for pid in pids:
        stat_data = parse_stat(pid)
        status = parse_status(pid)
        
        if not stat_data or not status:
            continue
        
        state = stat_data.get("state", "")
        proc_counts[state] = proc_counts.get(state, 0) + 1
        total_threads += int(status.get("Threads", "0"))
        
        if state == "Z":
            zombies += 1
        
        rss_pages = stat_data.get("rss", 0)
        rss_bytes = rss_pages * os.sysconf("SC_PAGE_SIZE") if rss_pages else 0
        
        top_cpu.append((stat_data.get("utime", 0) + stat_data.get("stime", 0), pid, status.get("Name", "")))
        top_rss.append((rss_bytes, pid, status.get("Name", "")))
    
    top_cpu_sorted = sorted(top_cpu, reverse=True)[:3]
    top_rss_sorted = sorted(top_rss, reverse=True)[:3]
    
    return {
        "items": {
            "loadavg": loadavg,
            "meminfo": memory,
            "uptime": uptime_seconds,
            "boot_time": read_text("/proc/stat"),
            "process_count_by_state": proc_counts,
            "threads_total": total_threads,
            "zombies": zombies,
            "top_cpu": [f"{name} ({pid})" for _, pid, name in top_cpu_sorted],
            "top_rss": [f"{name} ({pid})" for _, pid, name in top_rss_sorted],
        }
    }
