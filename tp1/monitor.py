#!/usr/bin/env python3
import curses
import grp
import os
import pwd
import signal
import select
import stat
import sys
import time
from collections import defaultdict
from multiprocessing import Event, Manager, Process, Queue, Value

SIGNAL_NAMES = {
    num: name
    for name, num in signal.__dict__.items()
    if name.startswith("SIG") and not name.startswith("SIG_")
}

VIEW_CONFIG = {
    "resumen": {"label": "Resumen", "default": 2.0, "minimum": 0.5},
    "memoria": {"label": "Memoria", "default": 3.0, "minimum": 1.0},
    "fds": {"label": "File Descriptors", "default": 5.0, "minimum": 2.0},
    "threads": {"label": "Threads", "default": 2.0, "minimum": 0.5},
    "senales": {"label": "Señales", "default": 10.0, "minimum": 5.0},
    "scheduling": {"label": "Scheduling", "default": 10.0, "minimum": 5.0},
    "sistema": {"label": "Sistema", "default": 2.0, "minimum": 1.0},
}

KEY_VIEW_MAP = {
    ord("1"): "resumen",
    ord("r"): "resumen",
    ord("2"): "memoria",
    ord("m"): "memoria",
    ord("3"): "fds",
    ord("f"): "fds",
    ord("4"): "threads",
    ord("t"): "threads",
    ord("5"): "senales",
    ord("s"): "senales",
    ord("6"): "scheduling",
    ord("p"): "scheduling",
    ord("7"): "sistema",
    ord("g"): "sistema",
}

SORT_MODES = ["cpu", "rss", "pid"]
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except OSError:
        return ""


def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.readlines()
    except OSError:
        return []


def list_pids():
    pids = []
    for name in os.listdir("/proc"):
        if name.isdigit():
            pids.append(int(name))
    return sorted(pids)


def parse_status(pid):
    data = {}
    for line in read_lines(f"/proc/{pid}/status"):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def parse_stat(pid):
    text = read_text(f"/proc/{pid}/stat").strip()
    if not text:
        return {}
    first_paren = text.find("(")
    last_paren = text.rfind(")")
    if first_paren == -1 or last_paren == -1 or first_paren >= last_paren:
        return {}
    prefix = text[:first_paren].strip()
    comm = text[first_paren + 1:last_paren]
    suffix = text[last_paren + 1:].split()
    if not prefix or not comm:
        return {}
    parts = [prefix, f"({comm})"] + suffix
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
    lines = read_lines(f"/proc/{pid}/sched")
    result = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def read_cmdline(pid):
    text = read_text(f"/proc/{pid}/cmdline")
    if not text:
        return ""
    return text.replace("\x00", " ").strip()


def get_username(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def decode_signal_mask(mask_text):
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
    segments = []
    for line in read_lines(f"/proc/{pid}/maps"):
        parts = line.split()
        if len(parts) < 5:
            continue
        address, perms, offset, dev, inode = parts[:5]
        pathname = " ".join(parts[5:]) if len(parts) >= 6 else ""
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
    path = f"/proc/{pid}/task"
    try:
        return [int(name) for name in os.listdir(path) if name.isdigit()]
    except OSError:
        return []


def syscall_get_total_jiffies():
    line = next((l for l in read_lines("/proc/stat") if l.startswith("cpu ")), "")
    if not line:
        return 0
    parts = line.split()[1:]
    return sum(int(x) for x in parts if x.isdigit())


def read_loadavg():
    text = read_text("/proc/loadavg").strip().split()
    if len(text) >= 3:
        return {
            "1m": text[0],
            "5m": text[1],
            "15m": text[2],
        }
    return {}


def read_meminfo():
    info = {}
    for line in read_lines("/proc/meminfo"):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        info[key.strip()] = value.strip()
    return info


def decode_fd_target(target):
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


def build_summary(pids, prev_cpu_data):
    total_jiffies = syscall_get_total_jiffies()
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
        prev = prev_cpu_data.get(pid, {})
        prev_proc_jiffies = prev.get("proc_jiffies", 0)
        prev_total = prev.get("total_jiffies", total_jiffies)
        proc_jiffies = stat_data["utime"] + stat_data["stime"]
        total_delta = total_jiffies - prev_total if prev_total else 1
        proc_delta = proc_jiffies - prev_proc_jiffies
        cpu_percent = (proc_delta / total_delta * 100.0) if total_delta > 0 else 0.0
        rss_pages = stat_data.get("rss", 0)
        rss_bytes = rss_pages * os.sysconf("SC_PAGE_SIZE") if rss_pages else 0
        summaries.append(
            {
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
            }
        )
        prev_cpu_data[pid] = {
            "proc_jiffies": proc_jiffies,
            "total_jiffies": total_jiffies,
            "updated": now,
        }
    return summaries


def build_memory_report(pids):
    report = {}
    for pid in pids:
        try:
            status = parse_status(pid)
            stat_data = parse_stat(pid)
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
            "minor_faults": str(stat_data.get("minor_faults", 0)),
            "major_faults": str(stat_data.get("major_faults", 0)),
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
                region = os.path.basename(name)
            # Calcular tamaño del segmento a partir del rango de direcciones (en bytes)
            try:
                addr_range = seg["address"].split('-')
                if len(addr_range) == 2:
                    start = int(addr_range[0], 16)
                    end = int(addr_range[1], 16)
                    size = end - start
                    by_region[region] += size
            except (ValueError, IndexError):
                pass
        memory["segments"] = [{"region": k, "bytes": v, "formatted": format_size(v)} for k, v in by_region.items()]
        report[pid] = memory
    return report


def build_fds_report(pids):
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
        report[pid] = {"pid": pid, "fds": fd_info, "cmd": read_cmdline(pid) or str(pid)}
    return report


def build_threads_report(pids, prev_thread_cpu):
    report = {}
    total_jiffies = syscall_get_total_jiffies()
    for pid in pids:
        thread_ids = read_task_ids(pid)
        threads = []
        for tid in thread_ids:
            try:
                stat_text = read_text(f"/proc/{pid}/task/{tid}/stat").strip()
                if not stat_text:
                    continue
                first_paren = stat_text.find("(")
                last_paren = stat_text.rfind(")")
                if first_paren == -1 or last_paren == -1 or first_paren >= last_paren:
                    continue
                prefix = stat_text[:first_paren].strip()
                comm = stat_text[first_paren + 1:last_paren]
                suffix = stat_text[last_paren + 1:].split()
                if not prefix or not comm:
                    continue
                parts = [prefix, f"({comm})"] + suffix
                if len(parts) < 24:
                    continue
                stat_data = {
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
                }
            except Exception:
                continue
            if not stat_data:
                continue
            # Leer status del thread para contexto switches
            thread_status = parse_status(f"{pid}/task/{tid}")
            prev = prev_thread_cpu.get((pid, tid), {})
            prev_proc = prev.get("proc_jiffies", 0)
            prev_total = prev.get("total_jiffies", total_jiffies)
            proc_jiffies = stat_data["utime"] + stat_data["stime"]
            total_delta = total_jiffies - prev_total if prev_total else 1
            proc_delta = proc_jiffies - prev_proc
            cpu_percent = (proc_delta / total_delta * 100.0) if total_delta > 0 else 0.0
            threads.append(
                {
                    "tid": tid,
                    "state": stat_data.get("state", ""),
                    "cpu_percent": round(cpu_percent, 2),
                    "name": stat_data.get("comm", ""),
                    "voluntary_ctxt_switches": thread_status.get("voluntary_ctxt_switches", "0"),
                    "nonvoluntary_ctxt_switches": thread_status.get("nonvoluntary_ctxt_switches", "0"),
                }
            )
            prev_thread_cpu[(pid, tid)] = {
                "proc_jiffies": proc_jiffies,
                "total_jiffies": total_jiffies,
            }
        report[pid] = {"pid": pid, "threads": threads, "cmd": read_cmdline(pid) or str(pid)}
    return report


def build_signals_report(pids):
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
    return report


def build_scheduling_report(pids):
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
    return report


def build_system_report(pids):
    memory = read_meminfo()
    loadavg = read_loadavg()
    uptime = read_text("/proc/uptime").split()
    uptime_seconds = float(uptime[0]) if uptime else 0.0
    proc_counts = defaultdict(int)
    total_threads = 0
    zombies = 0
    top_cpu = []
    top_rss = []

    total_jiffies = syscall_get_total_jiffies()
    for pid in pids:
        stat_data = parse_stat(pid)
        status = parse_status(pid)
        if not stat_data or not status:
            continue
        state = stat_data.get("state", "")
        proc_counts[state] += 1
        total_threads += int(status.get("Threads", "0"))
        if state == "Z":
            zombies += 1
        rss_pages = stat_data.get("rss", 0)
        rss_bytes = rss_pages * os.sysconf("SC_PAGE_SIZE") if rss_pages else 0
        top_cpu.append((stat_data.get("utime", 0) + stat_data.get("stime", 0), pid, status.get("Name", "")))
        top_rss.append((rss_bytes, pid, status.get("Name", "")))

    top_cpu_sorted = sorted(top_cpu, reverse=True)[:3]
    top_rss_sorted = sorted(top_rss, reverse=True)[:3]
    # Extraer btime de /proc/stat (boot time en segundos desde epoch)
    btime = "0"
    for line in read_lines("/proc/stat"):
        if line.startswith("btime "):
            btime = line.split()[1]
            break
    return {
        "loadavg": loadavg,
        "meminfo": memory,
        "uptime": uptime_seconds,
        "boot_time": btime,
        "process_count_by_state": dict(proc_counts),
        "threads_total": total_threads,
        "zombies": zombies,
        "top_cpu": ["%s (%s)" % (name, pid) for _, pid, name in top_cpu_sorted],
        "top_rss": ["%s (%s)" % (name, pid) for _, pid, name in top_rss_sorted],
        "total_jiffies": total_jiffies,
    }


def analyzer_loop(view_name, interval_value, pid_list, result_queue, shutdown_event):
    prev_data = {}
    while not shutdown_event.is_set():
        start = time.time()
        pids = list(pid_list)
        if view_name == "resumen":
            payload = {"items": build_summary(pids, prev_data)}
        elif view_name == "memoria":
            payload = {"items": build_memory_report(pids)}
        elif view_name == "fds":
            payload = {"items": build_fds_report(pids)}
        elif view_name == "threads":
            payload = {"items": build_threads_report(pids, prev_data)}
        elif view_name == "senales":
            payload = {"items": build_signals_report(pids)}
        elif view_name == "scheduling":
            payload = {"items": build_scheduling_report(pids)}
        elif view_name == "sistema":
            payload = build_system_report(pids)
        else:
            payload = {"items": {}}
        result_queue.put((view_name, payload))
        elapsed = time.time() - start
        sleep_time = max(0.05, interval_value.value - elapsed)
        if shutdown_event.wait(sleep_time):
            break


def pid_collector(pid_list, snapshot, shutdown_event):
    while not shutdown_event.is_set():
        pids = list_pids()
        pid_list[:] = pids
        snapshot["pids"] = pids
        if shutdown_event.wait(1.0):
            break


def aggregator_loop(snapshot, result_queue, shutdown_event):
    while not shutdown_event.is_set():
        try:
            view_name, payload = result_queue.get(timeout=0.5)
        except Exception:
            continue
        snapshot[view_name] = payload
        snapshot[f"{view_name}_ts"] = time.time()


def format_size(bytes_value):
    units = ["B", "KiB", "MiB", "GiB"]
    value = float(bytes_value)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} {units[-1]}"


def safe_addstr(window, y, x, text):
    height, width = window.getmaxyx()
    if y < 0 or y >= height or x < 0 or x >= width:
        return
    try:
        window.addstr(y, x, text[: max(0, width - x)])
    except curses.error:
        pass


def render_help(window):
    text = [
        "Teclas: 1/r Resumen, 2/m Memoria, 3/f FDs, 4/t Threads, 5/s Señales, 6/p Scheduling, 7/g Sistema",
        "↑/↓ Navegar | Enter Pin | / Filtrar comando | u Filtrar usuario | c Cambiar orden | +/- Ajustar intervalo",
        "q Salir | h/? Ayuda",
    ]
    for idx, line in enumerate(text, 1):
        safe_addstr(window, idx, 2, line)


def pick_process(snapshot, selected_index, filters, sort_mode, pinned_pid):
    resumen = snapshot.get("resumen", {}).get("items", [])
    items = resumen
    if filters["user"]:
        items = [item for item in items if item["user"] == filters["user"]]
    if filters["cmd"]:
        items = [item for item in items if filters["cmd"].lower() in item["cmd"].lower()]
    if sort_mode == "cpu":
        items = sorted(items, key=lambda item: item["cpu_percent"], reverse=True)
    elif sort_mode == "rss":
        items = sorted(items, key=lambda item: item["rss"], reverse=True)
    else:
        items = sorted(items, key=lambda item: item["pid"])
    if not items:
        return items, 0
    if pinned_pid is not None:
        for idx, item in enumerate(items):
            if item["pid"] == pinned_pid:
                return items, idx
    return items, min(max(0, selected_index), len(items) - 1)


def render_process_table(window, items, selected_index, offset):
    height, width = window.getmaxyx()
    headers = "PID   USER      CPU%   RSS     THREADS  CMD"
    safe_addstr(window, 1, 2, headers)
    if not items:
        safe_addstr(window, 3, 2, "No se encontraron procesos o aún no se cargaron los datos.")
        return
    for row_idx in range(height - 4):
        idx = offset + row_idx
        if idx >= len(items):
            break
        item = items[idx]
        line = f"{item['pid']:5} {item['user'][:8]:8} {item['cpu_percent']:6.2f} {format_size(item['rss']):7} {item['threads']:7}  {item['cmd'][: max(0, width - 40)]}"
        if idx == selected_index:
            try:
                window.addstr(row_idx + 2, 2, line[: width - 4], curses.A_REVERSE)
            except curses.error:
                pass
        else:
            safe_addstr(window, row_idx + 2, 2, line)


def render_detail(window, view_name, items, selected_pid, snapshot, selected_summary=None):
    height, width = window.getmaxyx()
    if view_name == "sistema":
        system = snapshot.get("sistema", {})
        y = 1
        safe_addstr(window, y, 2, f"Uptime: {system.get('uptime', 0):.1f}s")
        y += 1
        loadavg = system.get("loadavg", {})
        safe_addstr(window, y, 2, f"Load: {loadavg.get('1m', '0')} {loadavg.get('5m', '0')} {loadavg.get('15m', '0')}")
        y += 1
        meminfo = system.get("meminfo", {})
        for key in ["MemTotal", "MemFree", "Buffers", "Cached", "SwapTotal", "SwapFree"]:
            if key in meminfo:
                if y >= height - 1:
                    break
                safe_addstr(window, y, 2, f"{key}: {meminfo[key]}")
                y += 1
        if y < height - 1:
            safe_addstr(window, y, 2, f"Zombies: {system.get('zombies', 0)} | Threads: {system.get('threads_total', 0)}")
            y += 1
        if y < height - 1:
            safe_addstr(window, y, 2, f"Top CPU: {', '.join(system.get('top_cpu', []))}")
            y += 1
        if y < height - 1:
            safe_addstr(window, y, 2, f"Top RSS: {', '.join(system.get('top_rss', []))}")
        return
    if view_name == "resumen":
        if not selected_summary:
            safe_addstr(window, 1, 2, "Seleccione un proceso válido o espere a que se carguen los datos.")
            return
        y = 1
        safe_addstr(window, y, 2, f"PID: {selected_summary.get('pid')} CMD: {selected_summary.get('cmd', '')}")
        y += 1
        safe_addstr(window, y, 2, f"CPU%: {selected_summary.get('cpu_percent', 0):.2f} | RSS: {format_size(selected_summary.get('rss', 0))}")
        y += 1
        safe_addstr(window, y, 2, f"State: {selected_summary.get('state', '')} | Threads: {selected_summary.get('threads', 0)}")
        return
    process_data = items.get(selected_pid) if isinstance(items, dict) else None
    if not process_data:
        safe_addstr(window, 1, 2, "Seleccione un proceso válido o espere a que se carguen los datos.")
        return
    y = 1
    safe_addstr(window, y, 2, f"PID: {process_data.get('pid')} CMD: {process_data.get('cmd', '')}")
    y += 1
    if view_name == "memoria":
        safe_addstr(window, y, 2, f"VmSize: {process_data.get('vm_size')} | VmRSS: {process_data.get('vm_rss')}")
        y += 1
        safe_addstr(window, y, 2, f"VmData: {process_data.get('vm_data')} | VmStk: {process_data.get('vm_stk')}")
        y += 1
        safe_addstr(window, y, 2, f"VmExe: {process_data.get('vm_exe')} | VmLib: {process_data.get('vm_lib')}")
        y += 1
        safe_addstr(window, y, 2, f"VmHWM: {process_data.get('vm_hwm')} | VmSwap: {process_data.get('vm_swap')}")
        y += 1
        for seg in process_data.get("segments", [])[: max(0, height - y - 2)]:
            if y >= height - 1:
                break
            rendered = seg.get("formatted") or format_size(seg.get("bytes", 0))
            safe_addstr(window, y, 2, f"{seg['region']}: {rendered}")
            y += 1
        return
    if view_name == "fds":
        for entry in process_data.get("fds", [])[: max(0, height - y - 2)]:
            if y >= height - 1:
                break
            safe_addstr(window, y, 2, f"{entry['fd']:>4} {entry['type'][:8]:8} {entry['target'][: max(0, width - 20)]}")
            y += 1
        return
    if view_name == "threads":
        for thread in process_data.get("threads", [])[: max(0, height - y - 2)]:
            if y >= height - 1:
                break
            safe_addstr(window, y, 2, f"TID {thread['tid']:>5} {thread['name'][:20]:20} {thread['state']:2} {thread['cpu_percent']:6.2f}%")
            y += 1
        return
    if view_name == "senales":
        for key in ["SigBlk", "SigIgn", "SigCgt", "SigPnd", "ShdPnd"]:
            if y >= height - 1:
                break
            safe_addstr(window, y, 2, f"{key}: {', '.join(process_data.get(key, []))}")
            y += 1
        return
    if view_name == "scheduling":
        keys = ["nice", "priority", "policy", "rt_priority", "cpu_affinity", "voluntary_ctxt_switches", "nonvoluntary_ctxt_switches", "utime", "stime", "session", "pgid"]
        for key in keys:
            if y >= height - 1:
                break
            safe_addstr(window, y, 2, f"{key}: {process_data.get(key, '')}")
            y += 1
        return


def load_config(config_path=CONFIG_PATH):
    """Cargar configuración desde config.json."""
    config = {
        "intervals": {
            "resumen": 2.0,
            "memoria": 3.0,
            "fds": 5.0,
            "threads": 2.0,
            "senales": 10.0,
            "scheduling": 10.0,
            "sistema": 2.0,
        },
        "filters": {
            "cmd": "",
            "user": "",
        },
        "verbose": False,
    }
    try:
        import json
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    for key, value in loaded.items():
                        if key in ("intervals", "filters") and isinstance(value, dict):
                            config[key].update(value)
                        else:
                            config[key] = value
    except Exception:
        pass
    return config


def apply_runtime_config(config, intervals, filters, verbose_mode):
    config_intervals = config.get("intervals", {})
    for view in VIEW_CONFIG:
        raw_value = config_intervals.get(view, VIEW_CONFIG[view]["default"])
        try:
            interval_value = float(raw_value)
        except (TypeError, ValueError):
            interval_value = VIEW_CONFIG[view]["default"]
        intervals[view].value = max(VIEW_CONFIG[view]["minimum"], interval_value)

    config_filters = config.get("filters", {})
    if isinstance(config_filters, dict):
        filters["cmd"] = str(config_filters.get("cmd", filters.get("cmd", "")))
        filters["user"] = str(config_filters.get("user", filters.get("user", "")))

    return bool(config.get("verbose", verbose_mode))


def save_snapshot_dump(snapshot, dump_dir="."):
    """Guardar snapshot a dump_<timestamp>.json."""
    try:
        import json
        timestamp = int(time.time() * 1000)
        dump_path = os.path.join(dump_dir, f"dump_{timestamp}.json")
        # Convertir Manager.dict a dict normal
        dump_data = dict(snapshot)
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(dump_data, f, indent=2, default=str)
    except Exception:
        pass


def display_loop(snapshot, intervals, shutdown_event, signal_handler):
    curses.wrapper(lambda stdscr: run_display(stdscr, snapshot, intervals, shutdown_event, signal_handler))


def run_display(stdscr, snapshot, intervals, shutdown_event, signal_handler):
    curses.use_default_colors()
    stdscr.nodelay(True)
    stdscr.keypad(True)
    view_name = "resumen"
    selected = 0
    offset = 0
    pinned_pid = None
    filters = {"cmd": "", "user": ""}
    sort_mode = "cpu"
    show_help = False
    verbose_mode = False
    config = load_config()
    verbose_mode = apply_runtime_config(config, intervals, filters, verbose_mode)
    while not shutdown_event.is_set():
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        left_header = (
            f"Monitor de Procesos - Vista: {VIEW_CONFIG[view_name]['label']} | "
            f"Intervalo: {intervals[view_name].value:.1f}s | Orden: {sort_mode} | "
            f"Pinned: {pinned_pid or '-'} | {'VERBOSE' if verbose_mode else ''}"
        )
        right_header = f"Filtro: {filters['cmd'] or '-'} U: {filters['user'] or '-'}"
        safe_addstr(stdscr, 0, 2, left_header)
        right_col = max(2, width - len(right_header) - 2)
        safe_addstr(stdscr, 0, right_col, right_header)
        resumen_items, selected = pick_process(snapshot, selected, filters, sort_mode, pinned_pid)
        if selected < 0 and resumen_items:
            selected = 0
        if selected >= len(resumen_items):
            selected = max(0, len(resumen_items) - 1)
        if selected < offset:
            offset = selected
        if selected >= offset + max(1, height - 8):
            offset = selected - (height - 8) + 1
        render_process_table(stdscr.subwin(height - 8, width, 1, 0), resumen_items, selected, offset)
        stdscr.hline(height - 7, 0, "-", width)
        detail_win = stdscr.subwin(6, width, height - 6, 0)
        items = snapshot.get(view_name, {}).get("items", {})
        selected_pid = pinned_pid if pinned_pid else (resumen_items[selected]["pid"] if resumen_items else None)
        selected_summary = resumen_items[selected] if resumen_items else None
        render_detail(detail_win, view_name, items, selected_pid, snapshot, selected_summary)
        if show_help:
            help_win = stdscr.subwin(min(6, height - 1), width, height - 6, 0)
            render_help(help_win)
        stdscr.refresh()
        # Procesar señales via select (timeout = 0.1 para responsividad)
        sig = signal_handler.wait(timeout=0.1)
        if sig == signal.SIGINT or sig == signal.SIGTERM:
            shutdown_event.set()
            break
        elif sig == signal.SIGUSR1:
            save_snapshot_dump(snapshot)
        elif sig == signal.SIGHUP:
            config = load_config()
            verbose_mode = apply_runtime_config(config, intervals, filters, verbose_mode)
        elif sig == signal.SIGUSR2:
            verbose_mode = not verbose_mode
        # Procesar inputs del teclado
        key = stdscr.getch()
        if key == -1:
            time.sleep(0.05)
            continue
        if key in KEY_VIEW_MAP:
            view_name = KEY_VIEW_MAP[key]
        elif key in (ord("q"), 27):
            shutdown_event.set()
            break
        elif key in (ord("h"), ord("?")):
            show_help = not show_help
        elif key == curses.KEY_UP:
            selected = max(0, selected - 1)
        elif key == curses.KEY_DOWN:
            selected = min(len(resumen_items) - 1, selected + 1)
        elif key in (ord("c"),):
            next_idx = (SORT_MODES.index(sort_mode) + 1) % len(SORT_MODES)
            sort_mode = SORT_MODES[next_idx]
        elif key in (ord("\n"), curses.KEY_ENTER):
            if resumen_items:
                pinned_pid = resumen_items[selected]["pid"]
        elif key in (ord("+"), ord("=")):
            current = intervals[view_name].value
            intervals[view_name].value = max(VIEW_CONFIG[view_name]["minimum"], current - 0.5)
        elif key == ord("-"):
            intervals[view_name].value = intervals[view_name].value + 0.5
        elif key == ord("/"):
            curses.echo()
            curses.curs_set(1)
            stdscr.addstr(height - 1, 2, "Filtrar comando: ")
            stdscr.clrtoeol()
            cmd = stdscr.getstr(height - 1, 19, 40).decode("utf-8", errors="ignore")
            filters["cmd"] = cmd.strip()
            curses.noecho()
            curses.curs_set(0)
        elif key == ord("u"):
            curses.echo()
            curses.curs_set(1)
            stdscr.addstr(height - 1, 2, "Filtrar usuario: ")
            stdscr.clrtoeol()
            user = stdscr.getstr(height - 1, 18, 40).decode("utf-8", errors="ignore")
            filters["user"] = user.strip()
            curses.noecho()
            curses.curs_set(0)

class SignalHandler:
    """Manejador de señales usando self-pipe pattern (async-signal-safe)."""
    
    def __init__(self):
        self.pipe_read, self.pipe_write = os.pipe()
        os.set_blocking(self.pipe_write, False)
        os.set_blocking(self.pipe_read, False)
        self.signal_queue = []
        self.registered_signals = {}
    
    def _signal_handler(self, signum, frame):
        _ = frame
        try:
            os.write(self.pipe_write, bytes((signum & 0xFF,)))
        except (BlockingIOError, OSError):
            pass
    
    def register(self, signum, name=None):
        """Registrar una señal para manejar."""
        try:
            signal.signal(signum, self._signal_handler)
            self.registered_signals[signum] = name or f"SIG{signum}"
        except Exception:
            pass
    
    def wait(self, timeout=None):
        """Esperar señales de forma segura retornando las que se recibieron."""
        readable, _, _ = select.select([self.pipe_read], [], [], timeout)
        if self.pipe_read in readable:
            try:
                while True:
                    chunk = os.read(self.pipe_read, 1024)
                    if not chunk:
                        break
                    self.signal_queue.extend(chunk)
            except (BlockingIOError, OSError):
                pass
        return self.signal_queue.pop(0) if self.signal_queue else None
    
    def close(self):
        """Cerrar los pipes."""
        try:
            os.close(self.pipe_read)
            os.close(self.pipe_write)
        except OSError:
            pass


def install_signal_handlers(signal_handler):
    """Registrar los handlers de señales con self-pipe."""
    signal_handler.register(signal.SIGINT, "SIGINT")
    signal_handler.register(signal.SIGTERM, "SIGTERM")
    signal_handler.register(signal.SIGHUP, "SIGHUP")
    signal_handler.register(signal.SIGUSR1, "SIGUSR1")
    signal_handler.register(signal.SIGUSR2, "SIGUSR2")


def main():
    if not os.path.exists("/proc"):
        print("Este monitor requiere un sistema Linux con /proc montado.")
        sys.exit(1)
    manager = Manager()
    snapshot = manager.dict({
        "resumen": {},
        "memoria": {},
        "fds": {},
        "threads": {},
        "senales": {},
        "scheduling": {},
        "sistema": {},
        "pids": [],
    })
    pid_list = manager.list()
    result_queue = Queue()
    shutdown_event = Event()
    config = load_config()

    intervals = {}
    config_intervals = config.get("intervals", {})
    for view in VIEW_CONFIG:
        raw_value = config_intervals.get(view, VIEW_CONFIG[view]["default"])
        try:
            interval_value = float(raw_value)
        except (TypeError, ValueError):
            interval_value = VIEW_CONFIG[view]["default"]
        intervals[view] = Value("d", max(VIEW_CONFIG[view]["minimum"], interval_value))

    collector = Process(target=pid_collector, args=(pid_list, snapshot, shutdown_event), name="Collector")
    aggregator = Process(target=aggregator_loop, args=(snapshot, result_queue, shutdown_event), name="Aggregator")
    collectors = [collector, aggregator]

    analyzers = []
    for view in VIEW_CONFIG:
        proc = Process(
            target=analyzer_loop,
            args=(view, intervals[view], pid_list, result_queue, shutdown_event),
            name=f"Analyzer-{view}",
        )
        analyzers.append(proc)

    for proc in collectors + analyzers:
        proc.start()

    signal_handler = SignalHandler()
    install_signal_handlers(signal_handler)

    try:
        display_loop(snapshot, intervals, shutdown_event, signal_handler)
    except KeyboardInterrupt:
        shutdown_event.set()
    finally:
        shutdown_event.set()
        signal_handler.close()
        for proc in collectors + analyzers:
            proc.join(timeout=2.0)


if __name__ == "__main__":
    main()
