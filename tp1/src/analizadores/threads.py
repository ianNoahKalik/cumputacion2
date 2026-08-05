"""Analizador de Threads (LWPs)."""

from src.procfs import (
    parse_stat,
    parse_status,
    read_text,
    read_task_ids,
    system_cpu_total,
    read_cmdline,
)


def build_thread_snapshot(pids, previous_thread_cpu, total_delta, cpu_count):
    """Construye snapshot de threads de procesos."""
    report = {}
    total_jiffies = system_cpu_total()
    
    for pid in pids:
        thread_ids = read_task_ids(pid)
        threads = []
        
        for tid in thread_ids:
            try:
                stat_data = parse_stat(f"/proc/{pid}/task/{tid}/stat")
            except Exception:
                continue
            
            if not stat_data:
                continue
            
            comm = read_text(f"/proc/{pid}/task/{tid}/comm").strip()
            
            prev = previous_thread_cpu.get((pid, tid), {})
            prev_proc = prev.get("proc_jiffies", 0)
            prev_total = prev.get("total_jiffies", total_jiffies)
            
            proc_jiffies = stat_data["utime"] + stat_data["stime"]
            total_delta_actual = total_jiffies - prev_total if prev_total else 1
            proc_delta = proc_jiffies - prev_proc
            cpu_percent = (proc_delta / max(1, total_delta_actual) * 100.0) if total_delta_actual > 0 else 0.0
            
            status_data = parse_status(f"/proc/{pid}/task/{tid}")
            
            threads.append({
                "tid": tid,
                "state": stat_data.get("state", ""),
                "cpu_percent": round(cpu_percent, 2),
                "name": comm,
                "voluntary_ctxt_switches": status_data.get("voluntary_ctxt_switches", "0"),
                "nonvoluntary_ctxt_switches": status_data.get("nonvoluntary_ctxt_switches", "0"),
            })
            
            previous_thread_cpu[(pid, tid)] = {
                "proc_jiffies": proc_jiffies,
                "total_jiffies": total_jiffies,
            }
        
        report[pid] = {
            "pid": pid,
            "threads": threads,
            "cmd": read_cmdline(pid) or str(pid)
        }
    
    return {"items": report}
