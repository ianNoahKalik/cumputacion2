# Monitor de Procesos `/proc`

Este proyecto implementa un monitor multiproceso en Python que lee `/proc` directamente para mostrar información detallada de procesos, threads, memoria y scheduling.

## Estructura del Proyecto

```
tp1/
├── monitor.py              # Punto de entrada (wrapper)
├── src/
│   ├── __init__.py
│   ├── main.py             # Orquestación de procesos
│   ├── procfs.py           # Lectura y parseo de /proc
│   ├── recolector.py       # Recolector de PIDs
│   ├── agregador.py        # Agregador de datos
│   ├── display.py          # Interface TUI con curses
│   └── analizadores/       # Analizadores especializados
│       ├── resumen.py      # CPU%, RSS, threads, estado
│       ├── memoria.py      # VmSize, VmRSS, page faults
│       ├── fds.py          # File Descriptors
│       ├── threads.py      # Threads/LWPs
│       ├── senales.py      # Señales bloqueadas/ignoradas
│       ├── scheduling.py   # Nice, priority, policy
│       └── sistema.py      # Estadísticas globales
└── README.md
```

## Uso

Ejecutar en Linux con Python 3.11+:

```bash
python3 monitor.py
```

## Teclas principales

| Tecla | Acción |
|-------|--------|
| `1`–`7` / `r/m/f/t/s/p/g` | Cambiar vista |
| `↑` / `↓` | Navegar procesos |
| `Enter` | Fijar proceso seleccionado |
| `/` | Filtrar por comando |
| `u` | Filtrar por usuario |
| `c` | Cambiar ordenamiento (CPU/RSS/PID) |
| `+` / `-` | Ajustar intervalo de refresco |
| `q` | Salir |
| `h` / `?` | Ayuda |

## Arquitectura Multiproceso

- **Recolector**: mantiene lista de PIDs cada 1s
- **7 Analizadores**: procesos independientes, cada uno lee una dimensión
- **Agregador**: actualiza snapshot en memoria compartida
- **Display**: TUI interactiva que muestra datos del snapshot

## Vistas Disponibles

| Tecla | Vista | Datos |
|-------|-------|-------|
| `1` / `r` | **Resumen** | PID, CPU%, RSS, threads, estado |
| `2` / `m` | **Memoria** | VmSize, VmRSS, VmData, segmentos, page faults |
| `3` / `f` | **File Descriptors** | FDs abiertos, tipo, destino |
| `4` / `t` | **Threads** | TID, CPU%, estado, context switches |
| `5` / `s` | **Señales** | SigBlk, SigIgn, SigCgt, SigPnd, ShdPnd |
| `6` / `p` | **Scheduling** | Nice, priority, policy, CPU affinity |
| `7` / `g` | **Sistema** | Load, memoria, uptime, top 3 procesos |

## Requisitos

- Python 3.11+
- Linux con `/proc` montado
- Terminal compatible con `curses`

## Características

✅ Arquitectura multiproceso pura (lectura paralela de `/proc`)
✅ Sincronización con `multiprocessing.Manager` 
✅ Refresco diferenciado por vista (configurable en tiempo real)
✅ Lectura directa de `/proc` (sin dependencias externas)
✅ Snapshot global compartido en memoria
✅ Interface TUI responsive con filtrado y ordenamiento