"""Analizador de File Descriptors."""

import os

from src.procfs import (
    decode_fd_target,
    read_cmdline,
)


def build_fd_snapshot(pids):
    """Construye snapshot de file descriptors."""
    report = {}
    
    for pid in pids:
        fd_dir = f"/proc/{pid}/fd"
        try:
            entries = os.listdir(fd_dir)
        except OSError:
            continue
        
        fd_info = []
        for entry in sorted(entries, key=lambda x: int(x) if x.isdigit() else x):
            path = os.path.join(fd_dir, entry)
            try:
                target = os.readlink(path)
            except OSError:
                target = "<unavailable>"
            
            fd_info.append({
                "fd": entry,
                "target": target,
                "type": decode_fd_target(target),
            })
        
        report[pid] = {
            "pid": pid,
            "fds": fd_info,
            "cmd": read_cmdline(pid) or str(pid)
        }
    
    return {"items": report}
