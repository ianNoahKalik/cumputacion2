# Monitor de Procesos `/proc`

Este proyecto implementa un monitor multiproceso en Python que lee `/proc` directamente para mostrar:

- datos de resumen de procesos
- memoria y segmentos de cada proceso
- file descriptors abiertos
- threads / LWPs de cada proceso
- máscaras de señales
- información de scheduling
- estadísticas globales del sistema

## Uso

Ejecutar en Linux con Python 3.11+:

```bash
python monitor.py
```

### Teclas principales

- `1` / `r`: vista Resumen
- `2` / `m`: vista Memoria
- `3` / `f`: vista FDs
- `4` / `t`: vista Threads
- `5` / `s`: vista Señales
- `6` / `p`: vista Scheduling
- `7` / `g`: vista Sistema
- `↑` / `↓`: navegar lista de procesos
- `Enter`: fijar proceso seleccionado
- `/`: filtrar por comando
- `u`: filtrar por usuario
- `c`: alternar orden (CPU/RSS/PID)
- `+` / `-`: ajustar intervalo de refresco de la vista activa
- `q`: salir
- `h` / `?`: mostrar ayuda

## Arquitectura

- `collector`: mantiene la lista de PIDs de `/proc`
- `analyzers`: siete procesos independientes, uno por vista
- `aggregator`: actualiza el snapshot global en memoria compartida
- `display`: vista TUI en curses

## Requisitos

- Python 3.11+
- Linux con `/proc` montado
- Terminal compatible con `curses`
