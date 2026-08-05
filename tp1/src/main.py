"""Entry point del monitor dentro del paquete src."""

import multiprocessing as mp
import os
import queue
import signal
import sys
import time

from src.agregador import aggregator_loop
from src.analizadores.fds import build_fd_snapshot
from src.analizadores.memoria import build_memory_snapshot
from src.analizadores.resumen import build_resumen_snapshot
from src.analizadores.scheduling import build_scheduling_snapshot
from src.analizadores.senales import build_signal_snapshot
from src.analizadores.sistema import build_system_snapshot
from src.analizadores.threads import build_thread_snapshot
from src.display import display_loop, VIEW_CONFIG
from src.recolector import collector_loop
from src.procfs import system_cpu_total


MIN_REFRESH = {
    "resumen": 0.5,
    "memoria": 1.0,
    "fds": 2.0,
    "threads": 0.5,
    "senales": 5.0,
    "scheduling": 5.0,
    "sistema": 1.0,
}


def analyzer_loop(section, input_queue, output_queue, shutdown_event, interval_value):
    """Loop de un analizador específico."""
    cpu_count = os.cpu_count() or 1
    previous_cpu = {}
    previous_thread_cpu = {}
    pids = []
    last_emit = 0.0
    
    while not shutdown_event.is_set():
        # Intentar obtener lista de PIDs desde la cola
        try:
            while True:
                payload = input_queue.get_nowait()
                if isinstance(payload, dict) and "pids" in payload:
                    pids = [int(pid) for pid in payload["pids"] if isinstance(pid, (int, float)) or (isinstance(pid, str) and pid.isdigit())]
        except queue.Empty:
            pass
        except Exception:
            pass
        
        interval = max(float(interval_value.value), MIN_REFRESH[section])
        now = time.monotonic()
        
        if pids and now - last_emit >= interval:
            try:
                if section == "resumen":
                    result = build_resumen_snapshot(pids, previous_cpu, cpu_count)
                elif section == "memoria":
                    result = build_memory_snapshot(pids)
                elif section == "fds":
                    result = build_fd_snapshot(pids)
                elif section == "threads":
                    total_now = system_cpu_total()
                    previous_total = previous_cpu.get(-1, total_now)
                    previous_cpu[-1] = total_now
                    result = build_thread_snapshot(pids, previous_thread_cpu, max(1, total_now - previous_total), cpu_count)
                elif section == "senales":
                    result = build_signal_snapshot(pids)
                elif section == "scheduling":
                    result = build_scheduling_snapshot(pids)
                else:
                    result = build_system_snapshot(pids)
                
                result.update({"section": section, "seq": int(now * 1000)})
                
                # Limpiar la cola de salida (solo guardar el último resultado)
                try:
                    while True:
                        output_queue.get_nowait()
                except queue.Empty:
                    pass
                
                output_queue.put_nowait(result)
                last_emit = now
            except Exception:
                pass
        
        time.sleep(0.1)


def main():
    """Función principal del monitor."""
    if not os.path.exists("/proc"):
        print("Este monitor requiere un sistema Linux con /proc montado.")
        sys.exit(1)
    
    # Crear manager para memoria compartida
    manager = mp.Manager()
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
    
    # Cola para comunicar PIDs del recolector a los analizadores
    pid_queue = mp.Queue()
    
    # Cola para comunicar resultados de analizadores al agregador
    result_queue = mp.Queue()
    
    # Evento para shutdown
    shutdown_event = mp.Event()
    
    # Instalar manejadores de señales
    def signal_handler(signum, frame):
        shutdown_event.set()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Crear intervalos mutables (Value) para cada vista
    intervals = {
        view: mp.Value("d", VIEW_CONFIG[view]["default"]) for view in VIEW_CONFIG
    }
    
    # Crear procesos
    collector = mp.Process(
        target=collector_loop,
        args=(pid_queue, snapshot, shutdown_event),
        name="Collector",
        daemon=False
    )
    
    aggregator = mp.Process(
        target=aggregator_loop,
        args=(snapshot, result_queue, shutdown_event),
        name="Aggregator",
        daemon=False
    )
    
    analyzers = []
    for view in VIEW_CONFIG:
        proc = mp.Process(
            target=analyzer_loop,
            args=(view, pid_queue, result_queue, shutdown_event, intervals[view]),
            name=f"Analyzer-{view}",
            daemon=False
        )
        analyzers.append(proc)
    
    # Iniciar procesos
    collector.start()
    aggregator.start()
    for analyzer in analyzers:
        analyzer.start()
    
    try:
        # Mostrar display
        display_loop(snapshot, intervals, shutdown_event)
    except KeyboardInterrupt:
        shutdown_event.set()
    except Exception as e:
        print(f"Error en display: {e}", file=sys.stderr)
        shutdown_event.set()
    finally:
        # Shutdown limpio
        shutdown_event.set()
        
        # Esperar a procesos con timeout
        all_procs = [collector, aggregator] + analyzers
        for proc in all_procs:
            proc.join(timeout=2.0)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1.0)
        
        # Forzar terminar si sigue vivo
        for proc in all_procs:
            if proc.is_alive():
                proc.kill()
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
