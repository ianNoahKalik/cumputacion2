"""Recolector de PIDs: distribuye trabajo a los analizadores."""

from src.procfs import list_pids


def collector_loop(pid_queue, snapshot, shutdown_event):
    """Loop principal del recolector de PIDs."""
    while not shutdown_event.is_set():
        try:
            pids = list_pids()
            # Enviar PIDs al snapshot compartido
            snapshot["pids"] = pids
            
            # Enviar PIDs a través de la cola para los analizadores
            try:
                pid_queue.put({"pids": pids}, timeout=0.5)
            except Exception:
                pass
            
            # Esperar sin bloquear
            shutdown_event.wait(1.0)
        except Exception:
            if shutdown_event.wait(1.0):
                break
