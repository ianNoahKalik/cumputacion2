"""Analizador de Scheduling."""

from src.procfs import (
    parse_status,
    parse_stat,
    parse_sched,
    read_cmdline,
)


def build_scheduling_snapshot(pids):
    """Construye snapshot de scheduling de procesos."""
    report = {}
    
    for pid in pids:
        status = parse_status(pid)
        stat_data = parse_stat(pid)
        
        if not status or not stat_data:
            continue
        
        sched = parse_sched(pid)
        cpus_allowed = status.get("Cpus_allowed_list", "")
        
        report[pid] = {
            "pid": pid,
            "cmd": read_cmdline(pid) or status.get("Name", ""),
            "nice": status.get("Nice", str(stat_data.get("nice", 0))),
            "priority": stat_data.get("priority", 0),
            "policy": sched.get("sched_policy", str(stat_data.get("policy", 0))),
            "rt_priority": stat_data.get("rt_priority", 0),
            "cpu_affinity": cpus_allowed,
            "voluntary_ctxt_switches": status.get("voluntary_ctxt_switches", "0"),
            "nonvoluntary_ctxt_switches": status.get("nonvoluntary_ctxt_switches", "0"),
            "utime": stat_data.get("utime", 0),
            "stime": stat_data.get("stime", 0),
            "session": stat_data.get("session", 0),
            "pgid": stat_data.get("pgrp", 0),
        }
    
    return {"items": report}
