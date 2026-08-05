"""Analizador de Memoria: VmSize, VmRSS, segmentos, page faults."""

from collections import defaultdict

from src.procfs import (
    parse_status,
    parse_proc_maps,
    read_cmdline,
)


def build_memory_snapshot(pids):
    """Construye snapshot de memoria de procesos."""
    report = {}
    
    for pid in pids:
        try:
            status = parse_status(pid)
            segments = parse_proc_maps(pid)
        except Exception:
            continue
        
        if not status:
            continue
        
        memory = {
            "pid": pid,
            "cmd": read_cmdline(pid) or status.get("Name", ""),
            "vm_size": status.get("VmSize", "0 kB"),
            "vm_rss": status.get("VmRSS", "0 kB"),
            "vm_data": status.get("VmData", "0 kB"),
            "vm_stk": status.get("VmStk", "0 kB"),
            "vm_exe": status.get("VmExe", "0 kB"),
            "vm_lib": status.get("VmLib", "0 kB"),
            "vm_hwm": status.get("VmHWM", "0 kB"),
            "vm_swap": status.get("VmSwap", "0 kB"),
            "minor_faults": status.get("minflt", "0"),
            "major_faults": status.get("majflt", "0"),
            "segments": [],
        }
        
        by_region = defaultdict(int)
        for seg in segments:
            name = seg["pathname"]
            if name == "":
                region = seg["perms"]
            elif name == "[heap]":
                region = "heap"
            elif name == "[stack]":
                region = "stack"
            elif name == "[vdso]":
                region = "vdso"
            elif name == "[vvar]":
                region = "vvar"
            else:
                region = name.split("/")[-1]
            
            by_region[region] += 1
        
        memory["segments"] = [{"region": k, "count": v} for k, v in by_region.items()]
        report[pid] = memory
    
    return {"items": report}
