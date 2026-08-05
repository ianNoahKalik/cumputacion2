"""Display: interfaz TUI con curses."""

import curses
import time


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


def format_size(bytes_value):
    """Formatea tamaño en bytes a unidad legible."""
    units = ["B", "KiB", "MiB", "GiB"]
    value = float(bytes_value)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} {units[-1]}"


def safe_addstr(window, y, x, text):
    """Añade texto de forma segura sin exceder límites de ventana."""
    try:
        height, width = window.getmaxyx()
        if y < 0 or y >= height or x < 0 or x >= width:
            return
        text_truncated = text[: max(0, width - x)]
        window.addstr(y, x, text_truncated)
    except curses.error:
        pass


def render_help(window):
    """Renderiza pantalla de ayuda."""
    text = [
        "Teclas: 1/r Resumen, 2/m Memoria, 3/f FDs, 4/t Threads, 5/s Señales, 6/p Scheduling, 7/g Sistema",
        "↑/↓ Navegar | Enter Pin | / Filtrar comando | u Filtrar usuario | c Cambiar orden | +/- Ajustar intervalo",
        "q Salir | h/? Ayuda",
    ]
    for idx, line in enumerate(text, 1):
        safe_addstr(window, idx, 2, line)


def pick_process(snapshot, selected_index, filters, sort_mode, pinned_pid):
    """Selecciona proceso según filtros y ordenamiento."""
    resumen = snapshot.get("resumen", {}).get("items", [])
    items = list(resumen)
    
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
    """Renderiza tabla de procesos."""
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
        cmd_truncated = item["cmd"][: max(0, width - 40)]
        line = f"{item['pid']:5} {item['user'][:8]:8} {item['cpu_percent']:6.2f} {format_size(item['rss']):7} {item['threads']:7}  {cmd_truncated}"
        
        if idx == selected_index:
            try:
                window.addstr(row_idx + 2, 2, line[: width - 4], curses.A_REVERSE)
            except curses.error:
                pass
        else:
            safe_addstr(window, row_idx + 2, 2, line)


def render_detail(window, view_name, items, selected_pid, snapshot):
    """Renderiza panel de detalle según la vista."""
    height, width = window.getmaxyx()
    process_data = items.get(selected_pid) if isinstance(items, dict) else None
    
    if view_name == "sistema":
        sistema = snapshot.get("sistema", {}).get("items", {})
        y = 1
        safe_addstr(window, y, 2, f"Uptime: {sistema.get('uptime', 0):.1f}s")
        y += 1
        loadavg = sistema.get("loadavg", {})
        safe_addstr(window, y, 2, f"Load: {loadavg.get('1m', '0')} {loadavg.get('5m', '0')} {loadavg.get('15m', '0')}")
        y += 1
        meminfo = sistema.get("meminfo", {})
        for key in ["MemTotal", "MemFree", "Buffers", "Cached", "SwapTotal", "SwapFree"]:
            if key in meminfo and y < height - 1:
                safe_addstr(window, y, 2, f"{key}: {meminfo[key]}")
                y += 1
        if y < height - 1:
            safe_addstr(window, y, 2, f"Zombies: {sistema.get('zombies', 0)} | Threads: {sistema.get('threads_total', 0)}")
            y += 1
        if y < height - 1:
            top_cpu = sistema.get("top_cpu", [])
            safe_addstr(window, y, 2, f"Top CPU: {', '.join(top_cpu)}")
            y += 1
        if y < height - 1:
            top_rss = sistema.get("top_rss", [])
            safe_addstr(window, y, 2, f"Top RSS: {', '.join(top_rss)}")
        return
    
    if not process_data:
        safe_addstr(window, 1, 2, "Seleccione un proceso válido o espere a que se carguen los datos.")
        return
    
    y = 1
    safe_addstr(window, y, 2, f"PID: {process_data.get('pid')} CMD: {process_data.get('cmd', '')}")
    y += 1
    
    if view_name == "resumen":
        safe_addstr(window, y, 2, f"CPU%: {process_data.get('cpu_percent', 0):.2f} | RSS: {format_size(process_data.get('rss', 0))}")
        y += 1
        safe_addstr(window, y, 2, f"State: {process_data.get('state')} | Threads: {process_data.get('threads')}")
    
    elif view_name == "memoria":
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
            safe_addstr(window, y, 2, f"{seg['region']}: {seg['count']}")
            y += 1
    
    elif view_name == "fds":
        for entry in process_data.get("fds", [])[: max(0, height - y - 2)]:
            if y >= height - 1:
                break
            target_truncated = entry["target"][: max(0, width - 20)]
            safe_addstr(window, y, 2, f"{entry['fd']:>4} {entry['type'][:8]:8} {target_truncated}")
            y += 1
    
    elif view_name == "threads":
        for thread in process_data.get("threads", [])[: max(0, height - y - 2)]:
            if y >= height - 1:
                break
            name_truncated = thread["name"][:20]
            safe_addstr(window, y, 2, f"TID {thread['tid']:>5} {name_truncated:20} {thread['state']:2} {thread['cpu_percent']:6.2f}%")
            y += 1
    
    elif view_name == "senales":
        for key in ["SigBlk", "SigIgn", "SigCgt", "SigPnd", "ShdPnd"]:
            if y >= height - 1:
                break
            signals = ", ".join(process_data.get(key, []))
            safe_addstr(window, y, 2, f"{key}: {signals}")
            y += 1
    
    elif view_name == "scheduling":
        keys = ["nice", "priority", "policy", "rt_priority", "cpu_affinity", "voluntary_ctxt_switches", "nonvoluntary_ctxt_switches", "utime", "stime"]
        for key in keys:
            if y >= height - 1:
                break
            safe_addstr(window, y, 2, f"{key}: {process_data.get(key, '')}")
            y += 1


def display_process_entry(entry):
    """Wrapper para mantener compatibilidad si es necesario."""
    return entry


def run_display(stdscr, snapshot, intervals, shutdown_event):
    """Loop principal del display."""
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
    
    while not shutdown_event.is_set():
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        
        # Header
        header = f"Monitor de Procesos - Vista: {VIEW_CONFIG[view_name]['label']} | Intervalo: {intervals[view_name].value:.1f}s | Orden: {sort_mode} | Pinned: {pinned_pid or '-'}"
        safe_addstr(stdscr, 0, 2, header)
        safe_addstr(stdscr, 0, max(0, width - 30), f"Filtro: {filters['cmd'] or '-'} U: {filters['user'] or '-'}")
        
        # Obtener lista de procesos
        resumen_items, selected = pick_process(snapshot, selected, filters, sort_mode, pinned_pid)
        
        if selected < 0 and resumen_items:
            selected = 0
        if selected >= len(resumen_items):
            selected = max(0, len(resumen_items) - 1)
        
        if selected < offset:
            offset = selected
        if selected >= offset + max(1, height - 8):
            offset = selected - (height - 8) + 1
        
        # Tabla de procesos
        table_win = stdscr.subwin(height - 8, width, 1, 0)
        render_process_table(table_win, resumen_items, selected, offset)
        
        # Separador
        stdscr.hline(height - 7, 0, "-", width)
        
        # Panel de detalle
        detail_win = stdscr.subwin(6, width, height - 6, 0)
        items = snapshot.get(view_name, {}).get("items", {})
        selected_pid = pinned_pid if pinned_pid else (resumen_items[selected]["pid"] if resumen_items else None)
        render_detail(detail_win, view_name, items, selected_pid, snapshot)
        
        # Ayuda
        if show_help:
            help_win = stdscr.subwin(min(6, height - 1), width, height - 6, 0)
            render_help(help_win)
        
        stdscr.refresh()
        
        # Procesar input
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
            selected = min(len(resumen_items) - 1, selected + 1) if resumen_items else 0
        elif key == ord("c"):
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
            try:
                stdscr.addstr(height - 1, 2, "Filtrar comando: ")
                stdscr.clrtoeol()
                cmd = stdscr.getstr(height - 1, 19, 40).decode("utf-8", errors="ignore")
                filters["cmd"] = cmd.strip()
            except curses.error:
                pass
            finally:
                curses.noecho()
                curses.curs_set(0)
        elif key == ord("u"):
            curses.echo()
            curses.curs_set(1)
            try:
                stdscr.addstr(height - 1, 2, "Filtrar usuario: ")
                stdscr.clrtoeol()
                user = stdscr.getstr(height - 1, 18, 40).decode("utf-8", errors="ignore")
                filters["user"] = user.strip()
            except curses.error:
                pass
            finally:
                curses.noecho()
                curses.curs_set(0)


def display_loop(snapshot, intervals, shutdown_event):
    """Inicia el loop de display."""
    curses.wrapper(lambda stdscr: run_display(stdscr, snapshot, intervals, shutdown_event))
