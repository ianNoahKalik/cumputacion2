"""Helpers para lectura y parseo de /proc."""

import os
import signal
from collections import defaultdict


SIGNAL_NAMES = {
    num: name
    for name, num in signal.__dict__.items()
    if name.startswith("SIG") and not name.startswith("SIG_")
}


def read_text(path):
    """Lee un archivo de texto de /proc."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def read_lines(path):
    """Lee líneas de un archivo de /proc."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.readlines()
    except OSError:
        return []


def list_pids():
    """Lista todos los PIDs activos en el sistema."""
    pids = []
    try:
        for name in os.listdir("/proc"):
            if name.isdigit():
                pids.append(int(name))
    except OSError:
        return []
    return sorted(pids)


def parse_status(pid):
    """Parsea /proc/<pid>/status."""
    data = {}
    for line in read_lines(f"/proc/{pid}/status"):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def parse_stat(pid):
    """Parsea /proc/<pid>/stat."""
    text = read_text(f"/proc/{pid}/stat").strip()
    if not text:
        return {}
    
    parts = text.split()
    if len(parts) < 24:
        return {}
    
    data = {
        "pid": int(parts[0]),
        "comm": parts[1].strip("()"),
        "state": parts[2],
        "ppid": int(parts[3]),
        "pgrp": int(parts[4]),
        "session": int(parts[5]),
        "utime": int(parts[13]),
        "stime": int(parts[14]),
        "cutime": int(parts[15]),
        "cstime": int(parts[16]),
        "priority": int(parts[17]),
        "nice": int(parts[18]),
        "num_threads": int(parts[19]),
        "starttime": int(parts[21]),
        "vsize": int(parts[22]),
        "rss": int(parts[23]),
        "minor_faults": int(parts[9]),
        "major_faults": int(parts[11]),
        "policy": int(parts[40]) if len(parts) > 40 else 0,
        "rt_priority": int(parts[39]) if len(parts) > 39 else 0,
    }
    return data


def parse_sched(pid):
    """Parsea /proc/<pid>/sched."""
    lines = read_lines(f"/proc/{pid}/sched")
    result = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def read_cmdline(pid):
    """Lee el comando completo de /proc/<pid>/cmdline."""
    text = read_text(f"/proc/{pid}/cmdline")
    if not text:
        return ""
    return text.replace("\x00", " ").strip()


def get_username(uid):
    """Obtiene el nombre de usuario a partir del UID."""
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (KeyError, ImportError):
        return str(uid)


def decode_signal_mask(mask_text):
    """Decodifica una máscara de señales hexadecimal."""
    try:
        mask = int(mask_text, 16)
    except ValueError:
        return []
    names = []
    for sig_num in range(1, 65):
        if mask & (1 << (sig_num - 1)):
            names.append(SIGNAL_NAMES.get(sig_num, f"SIG{sig_num}"))
    return names


def parse_proc_maps(pid):
    """Parsea /proc/<pid>/maps."""
    segments = []
    for line in read_lines(f"/proc/{pid}/maps"):
        parts = line.split()
        if len(parts) < 5:
            continue
        address, perms, offset, dev, inode = parts[:5]
        pathname = parts[5] if len(parts) >= 6 else ""
        segments.append({
            "address": address,
            "perms": perms,
            "offset": offset,
            "dev": dev,
            "inode": inode,
            "pathname": pathname,
        })
    return segments


def read_task_ids(pid):
    """Lee los IDs de threads de /proc/<pid>/task."""
    path = f"/proc/{pid}/task"
    try:
        return sorted([int(name) for name in os.listdir(path) if name.isdigit()])
    except OSError:
        return []


def system_cpu_total():
    """Obtiene el total de jiffies del CPU del sistema."""
    line = next((l for l in read_lines("/proc/stat") if l.startswith("cpu ")), "")
    if not line:
        return 0
    parts = line.split()[1:]
    return sum(int(x) for x in parts if x.isdigit())


def read_loadavg():
    """Lee /proc/loadavg."""
    text = read_text("/proc/loadavg").strip().split()
    if len(text) >= 3:
        return {
            "1m": text[0],
            "5m": text[1],
            "15m": text[2],
        }
    return {}


def read_meminfo():
    """Lee /proc/meminfo."""
    info = {}
    for line in read_lines("/proc/meminfo"):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        info[key.strip()] = value.strip()
    return info


def decode_fd_target(target):
    """Decodifica el tipo de un file descriptor."""
    if target.startswith("socket:"):
        return "socket"
    if target.startswith("pipe:"):
        return "pipe"
    if target.startswith("anon_inode:"):
        return "anon_inode"
    if target.startswith("/dev/"):
        return "device"
    if target.startswith("/tmp"):
        return "file"
    return "file"
