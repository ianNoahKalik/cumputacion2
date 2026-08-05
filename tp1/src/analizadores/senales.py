"""Analizador de Señales."""

from src.procfs import (
    parse_status,
    decode_signal_mask,
    read_cmdline,
)


def build_signal_snapshot(pids):
    """Construye snapshot de señales de procesos."""
    report = {}
    
    for pid in pids:
        status = parse_status(pid)
        if not status:
            continue
        
        report[pid] = {
            "pid": pid,
            "cmd": read_cmdline(pid) or status.get("Name", ""),
            "SigBlk": decode_signal_mask(status.get("SigBlk", "0")),
            "SigIgn": decode_signal_mask(status.get("SigIgn", "0")),
            "SigCgt": decode_signal_mask(status.get("SigCgt", "0")),
            "SigPnd": decode_signal_mask(status.get("SigPnd", "0")),
            "ShdPnd": decode_signal_mask(status.get("ShdPnd", "0")),
        }
    
    return {"items": report}
