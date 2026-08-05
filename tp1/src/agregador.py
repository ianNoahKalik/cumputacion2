"""Agregador: recopila datos de analizadores en snapshot compartido."""

import time


def aggregator_loop(snapshot, result_queue, shutdown_event):
    """Loop principal del agregador."""
    while not shutdown_event.is_set():
        try:
            # Intentar obtener resultado de algún analizador
            result = result_queue.get(timeout=0.5)
            
            section = result.get("section")
            if section:
                # Actualizar snapshot con los datos del analizador
                snapshot[section] = result
                snapshot[f"{section}_ts"] = time.time()
        except Exception:
            # Timeout o error, continuar
            pass
        
        if shutdown_event.is_set():
            break
