#!/usr/bin/env bash
# Agente para ab_run.py --agent-cmd: prompt por stdin -> Zig por stdout.
# Corre `opencode run` (modelo AB_MODEL, por defecto opencode/big-pickle) en el
# cwd temporal del intento y le pide escribir la solucion en ./solution.zig.
# rc != 0 si opencode falla o no deja solution.zig (=> AGENT_ERROR en el arnes).
set -u
model="${AB_MODEL:-opencode/big-pickle}"
cat > prompt.txt
instr="Lee la tarea en ./prompt.txt y resuélvela. Escribe el código Zig final en el archivo ./solution.zig (solo código, sin cercas markdown). Puedes usar la shell (zig 0.16.0 está instalado). No leas fuera de este directorio salvo lo que la tarea permita."
opencode run -m "$model" --format default "$instr" >&2 2>&1
rc=$?
[ "$rc" -eq 0 ] || exit "$rc"
[ -s solution.zig ] || { echo "ab_agent_opencode: sin solution.zig" >&2; exit 3; }
cat solution.zig
