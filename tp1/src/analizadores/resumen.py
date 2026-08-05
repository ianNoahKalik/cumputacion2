"""Analizador de Resumen: estado, CPU, RSS, threads, comando."""

import os
import time

from src.procfs import (
    parse_stat,
    parse_status,
    read_cmdline,
    system_cpu_total,
    get_username,
)


def build_resumen_snapshot(pids, previous_cpu, cpu_count):
    """Construye snapshot del resumen de procesos."""
    total_jiffies = system_cpu_total()
    now = time.time()
    summaries = []
    
    for pid in pids:
        try:
            status = parse_status(pid)
            stat_data = parse_stat(pid)
        except Exception:
            continue
        
        if not stat_data:
            continue
        
        uid = int(status.get("Uid", "0").split()[0]) if status.get("Uid") else 0
        user = get_username(uid)
        cmd = read_cmdline(pid) or stat_data.get("comm", "")
        
        prev = previous_cpu.get(pid, {})
        prev_proc_jiffies = prev.get("proc_jiffies", 0)
        prev_total = prev.get("total_jiffies", total_jiffies)
        
        proc_jiffies = stat_data["utime"] + stat_data["stime"]
        total_delta = total_jiffies - prev_total if prev_total else 1
        proc_delta = proc_jiffies - prev_proc_jiffies
        cpu_percent = (proc_delta / total_delta * 100.0) if total_delta > 0 else 0.0
        
        rss_pages = stat_data.get("rss", 0)
        rss_bytes = rss_pages * os.sysconf("SC_PAGE_SIZE") if rss_pages else 0
        
        summaries.append({
            "pid": pid,
            "ppid": stat_data.get("ppid", 0),
            "user": user,
            "uid": uid,
            "state": stat_data.get("state", ""),
            "cmd": cmd,
            "cpu_percent": round(cpu_percent, 2),
            "threads": int(status.get("Threads", "0")),
            "rss": rss_bytes,
            "vsize": stat_data.get("vsize", 0),
        })
        
        previous_cpu[pid] = {
            "proc_jiffies": proc_jiffies,
            "total_jiffies": total_jiffies,
            "updated": now,
        }
    
    return {"items": summaries}
