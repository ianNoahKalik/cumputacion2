# Monitor de Procesos y Threads `/proc`

**Computación II · 2026 · Ian Kalik**

Monitor multiproceso en Python que inspecciona `/proc` de Linux para mostrar estado detallado de procesos, threads, memoria, file descriptors, señales y scheduling en una interfaz interactiva basada en curses.

---

## Tabla de Contenidos

1. [Objetivos Pedagógicos](#objetivos-pedagógicos)
2. [Arquitectura](#arquitectura)
3. [Decisiones de Diseño](#decisiones-de-diseño)
4. [Conceptos del Curso Aplicados](#conceptos-del-curso-aplicados)
5. [Características Implementadas](#características-implementadas)
6. [Requisitos Técnicos](#requisitos-técnicos)
7. [Cómo Correr y Testear](#cómo-correr-y-testear)
8. [Señales del Monitor](#señales-del-monitor)
9. [Limitaciones Conocidas](#limitaciones-conocidas)

---

## Objetivos Pedagógicos

Al completar este proyecto, el aprendizaje abarca:

### 1. **Lectura de `/proc` desde userspace**
   - Inspeccionar procesos sin dependencias externas (sin `ps`, `top`, etc.)
   - Parsear archivos de formato variable (`/proc/<pid>/stat`, `/proc/<pid>/status`, `/proc/<pid>/maps`)
   - Manejar edge cases: procesos con nombres que contienen espacios, paths exóticos, etc.

### 2. **Diseño multiproceso con IPC**
   - Distribuir trabajo entre procesos independientes (recolector + 7 analizadores)
   - Usar `multiprocessing.Queue` y memoria compartida (`Manager.dict`) para comunicación
   - Sincronizar con `Event` para shutdown limpio
   - Evitar race conditions en acceso a estructuras compartidas

### 3. **Manejo de señales asíncronas**
   - Implementar el patrón **self-pipe** para manejadores async-signal-safe
   - SIGINT/SIGTERM para shutdown limpio
   - SIGHUP para recargar configuración
   - SIGUSR1/SIGUSR2 para volcado de estado y modo verbose

### 4. **Interfaz de usuario interactiva**
   - TUI en curses con múltiples vistas alternables
   - Navegación con flechas, búsqueda por comando/usuario
   - Reordenamiento dinámico (CPU, RSS, PID)
   - Pin de proceso para seguimiento

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│           SNAPSHOT GLOBAL (Manager.dict compartido)        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ "resumen"   : {items: [...]}  "resumen_ts"    : 123 │   │
│  │ "memoria"   : {items: {...}}  "memoria_ts"    : 123 │   │
│  │ "fds"       : {items: {...}}  "fds_ts"        : 123 │   │
│  │ "threads"   : {items: {...}}  "threads_ts"    : 123 │   │
│  │ "senales"   : {items: {...}}  "senales_ts"    : 123 │   │
│  │ "scheduling": {items: {...}}  "scheduling_ts" : 123 │   │
│  │ "sistema"   : {items: {...}}  "sistema_ts"    : 123 │   │
│  │ "pids"      : [1, 2, 3, ...]                        │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Componentes:**

- **Recolector:** Lista PIDs cada 1s desde `/proc`, actualiza `pid_list`
- **7 Analizadores:** Cada uno procesa una vista (Resumen, Memoria, FDs, Threads, Señales, Scheduling, Sistema)
- **Agregador:** Consume `result_queue`, actualiza snapshot global
- **Display (TUI):** Main thread, renderiza en curses, procesa input, maneja señales
- **SignalHandler:** Self-pipe pattern para SIGINT/TERM/HUP/USR1/USR2 (async-signal-safe)

---

## Decisiones de Diseño

### 1. **Una `pid_list` compartida (no colas individuales)**

**Decisión:** Un único `manager.list()` que todos los analizadores leen.

**Justificación:**
- La lista de PIDs **no es trabajo a repartir**, es **estado que todos necesitan**.
- Con `Queue`, cada item lo recibe UN consumidor (causaba race condition en versión anterior).
- **Trade-off:** Mayor memoria compartida vs. código más simple y correcto.

### 2. **`result_queue` para publicar resultados**

**Decisión:** Los analizadores publican `(view_name, payload)` en una cola compartida.

**Justificación:** Desacople, el agregador procesa cuando puede sin bloquear.

### 3. **Self-pipe pattern para señales**

**Decisión:** Handler solo escribe 1 byte al pipe; trabajo real en main loop.

**Justificación:**
- **Async-signal-safe:** El handler es mínimo (solo `os.write()`).
- No hay riesgo de deadlock si la señal interrumpe una llamada que toma locks.
- JSON dump (SIGUSR1) se hace en main loop, no en el handler.

### 4. **Intervalos por vista con `Value("d", ...)`**

**Decisión:** Cada vista tiene su propio interval, modificable con `+`/`-` en runtime.

**Justificación:** Usuarios pueden querer refresco rápido en CPU pero lento en memoria.

### 5. **config.json centralizado**

**Archivo:** `config.json` en la raíz del proyecto.

**Carga:** Al inicio y en SIGHUP, sin reiniciar.

**Contenido:** Intervalos, filtros default, flag verbose.

### 6. **Dump a `dump_<timestamp>.json`**

**Ubicación:** Mismo directorio que el proceso.

**Contenido:** Todo el snapshot global en JSON.

**Justificación:** Timestamp evita sobrescrituras, JSON es estándar.

### 7. **Parse_stat con rfind(')')**

**Problema:** `text.split()` falla si `comm` tiene espacios (ej: "Web Content").

**Solución:** El último `)` siempre cierra COMM.

```python
last_paren = text.rfind(')')
prefix = text[:last_paren + 1]
suffix = text[last_paren + 1:].split()
```

**Justificación:** Robusto incluso con espacios/paréntesis en nombres de procesos.

---

## Conceptos del Curso Aplicados

Esta sección conecta decisiones concretas de implementación con temas vistos en clase.

### Clase 3: Procesos, anatomía y `/proc`
- El monitor extrae estado, memoria, scheduling y señales leyendo directamente `/proc/<pid>/stat`, `/proc/<pid>/status`, `/proc/<pid>/maps`, `/proc/<pid>/sched`.
- No se usa `psutil` ni wrappers externos: la lectura se hace con parseo manual de archivos del kernel.

### Clase 4: Ciclo de vida de procesos (fork/exec/wait, zombies)
- En la vista Sistema se contabilizan procesos por estado y zombies, leyendo el campo `state` de cada proceso.
- Esto permite observar en tiempo real procesos terminados no recolectados por su padre.

### Clase 5: File descriptors e IPC por descriptores
- La vista FDs inspecciona `/proc/<pid>/fd` y resuelve symlinks para tipificar `socket`, `pipe`, `anon_inode`, `file`.
- Se visualiza la relación entre descriptors y recursos del kernel.

### Clase 6: Señales y async-signal-safe
- El manejo de señales usa self-pipe: el handler escribe al pipe y el loop principal procesa la acción.
- Se implementan `SIGINT`, `SIGTERM`, `SIGHUP`, `SIGUSR1`, `SIGUSR2` sin hacer trabajo pesado dentro del handler.

### Clases 8 y 9: Multiprocessing e IPC en Python
- Arquitectura multiproceso: recolector, 7 analizadores y agregador como procesos independientes.
- IPC mixto: `Manager.dict` para snapshot global compartido, `Manager.list` para lista de PIDs y `Queue` para resultados de analizadores.
- La lista de PIDs se modela como estado compartido (no como trabajo a repartir), evitando starvation por consumidores múltiples.

### Clase 10: Threads y LWPs
- La vista Threads recorre `/proc/<pid>/task/<tid>` para listar LWPs reales del proceso.
- Se calcula CPU por thread con deltas de jiffies y se muestran context switches voluntarios e involuntarios.

---

## Características Implementadas

### ✅ **7 Vistas Obligatorias**

| # | Tecla | Vista | Datos | Intervalo |
|---|-------|-------|-------|-----------|
| 1 | `1`/`r` | **Resumen** | PID, CPU%, RSS, threads, comando, usuario | 2.0s |
| 2 | `2`/`m` | **Memoria** | VmSize/RSS/Data/Stack, page faults, segmentos (bytes) | 3.0s |
| 3 | `3`/`f` | **FDs** | FD, target (archivo/socket/pipe/etc) | 5.0s |
| 4 | `4`/`t` | **Threads** | TID, CPU%, estado, context switches | 2.0s |
| 5 | `5`/`s` | **Señales** | SigBlk, SigIgn, SigCgt, SigPnd, ShdPnd (decodificadas) | 10.0s |
| 6 | `6`/`p` | **Scheduling** | Nice, priority, policy, RT priority, CPU affinity | 10.0s |
| 7 | `7`/`g` | **Sistema** | Uptime, loadavg, meminfo, zombies, threads, top 3 CPU/RSS | 2.0s |

### ✅ **Navegación y Interacción**

| Tecla | Acción |
|-------|--------|
| `↑` / `↓` | Navegar procesos (scroll automático) |
| `Enter` | Pin proceso (sigue incluso si reordena) |
| `/` | Filtro por comando (prompt interactivo) |
| `u` | Filtro por usuario (prompt interactivo) |
| `c` | Ciclar orden (CPU → RSS → PID) |
| `+` / `-` | Ajustar intervalo de vista activa |
| `h` / `?` | Mostrar/ocultar ayuda |
| `q` / `Esc` | Salir |

### ✅ **Señales (Async-Signal-Safe)**

| Señal | Acción |
|-------|--------|
| **SIGINT** (Ctrl+C) | Shutdown limpio |
| **SIGTERM** | Shutdown limpio |
| **SIGHUP** | Recargar `config.json` |
| **SIGUSR1** | Dump a `dump_<timestamp>.json` |
| **SIGUSR2** | Toggle verbose mode |

---

## Requisitos Técnicos

### Sistema
- **Linux** con `/proc` montado
- **Python 3.11+**
- **Docker** y **Docker Compose** (recomendado)

### Dependencias
- Todas stdlib Python 3: `curses`, `multiprocessing`, `signal`, `os`, `select`, `json`
- Nada más - proyecto puro Python.

---

## Cómo Correr y Testear

### Ejecución en Docker (recomendado)

```bash
cd tp1
docker compose up --build
```

### Ejecución Local

```bash
pip install -r requirements.txt
python monitor.py
```

### Tests manuales mínimos (checklist)

1. **Arranque correcto**
   - `docker compose up --build`
   - Esperado: se abre la TUI y aparecen procesos en la tabla superior.

2. **Navegación y vistas**
   - Probar `1..7`, flechas, `Enter`, `/`, `u`, `c`, `+`, `-`, `h`, `q`.
   - Esperado: cambia la vista activa y responde cada keybinding obligatorio.

3. **SIGHUP (reload config)**
   - En otra terminal: `docker compose kill -s HUP monitor`
   - Esperado: el monitor sigue vivo y aplica configuración recargada.

4. **SIGUSR1 (dump snapshot)**
   - En otra terminal: `docker compose kill -s USR1 monitor`
   - Esperado: se crea `dump_<timestamp>.json` en el directorio del proyecto.

5. **SIGUSR2 (toggle verbose)**
   - En otra terminal: `docker compose kill -s USR2 monitor`
   - Esperado: cambia el estado de verbose en el header de la TUI.

6. **Shutdown limpio**
   - `q` desde la TUI o `docker compose down`
   - Esperado: finalizan procesos hijos y se libera la red/contenedor.

### Navegación en la TUI

- **Flechas `↑`/`↓`**: cambiar proceso
- **Números `1-7` o letras `r/m/f/t/s/p/g`**: cambiar vista
- **`/`**: filtro por comando
- **`u`**: filtro por usuario
- **`c`**: reordenar (CPU → RSS → PID)
- **`+`/`-`**: ajustar intervalo
- **`Enter`**: pin proceso
- **`h`**: mostrar ayuda
- **`q`**: salir

### Señales desde otra terminal

```bash
MONITOR_PID=$(pidof python)  # O el PID del contenedor

# Recargar config
kill -HUP $MONITOR_PID

# Dump snapshot
kill -USR1 $MONITOR_PID  # Genera dump_<timestamp>.json

# Toggle verbose
kill -USR2 $MONITOR_PID

# Shutdown
kill -TERM $MONITOR_PID
```

---

## Señales del Monitor

Todos los handlers implementan **self-pipe pattern** (clase 6 del curso).

### SIGINT / SIGTERM
Shutdown limpio: cierra procesos hijos, limpia display, vacía buffers.

### SIGHUP
Recarga `config.json` dinámicamente sin reiniciar el monitor.

### SIGUSR1
Genera `dump_<timestamp>.json` con snapshot completo para debugging/logging.

### SIGUSR2
Alterna `verbose_mode` (flag visible en header, extensible para más detalles).

---

## Limitaciones Conocidas

### 1. **Threads efímeros**
Si un thread termina entre lectura y parseo, devuelve datos vacíos. Esto es inherente a `/proc`.

### 2. **Segmentos sin tamaño**
Si el parse de direcciones hexadecimales falla raramente, el segmento suma 0 bytes.

### 3. **Verbose mode sin detalles aún**
Flag se alterna con SIGUSR2, pero lógica de qué mostrar extra es futura extensión.

### 4. **CPU% es aproximada**
Calculado como `(proc_jiffies_delta / total_jiffies_delta) * 100`. Puede variar con jitter del sistema.

### 5. **FDs deletreados**
Si un archivo se elimina pero el FD sigue abierto, mostramos `<nombre>`.

---

*Monitor de Procesos - Computación II 2026 · UdeMM*
