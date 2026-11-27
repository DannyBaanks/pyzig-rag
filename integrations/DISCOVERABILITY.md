# Medición de descubribilidad

## Cambios

- `pyzig/mcp_server.py`: las instrucciones y descripciones dicen cuándo consultar: antes de portar Python a Zig 0.16, antes de usar `std.Io`, `ArrayList` o `build.zig`, y después de un error de compilación. El error exacto se pega en `pyzig_search.intent`; `pyzig_check` recibe el fragmento Zig para compilarlo y sugerir recetas. Se añadieron descripciones a los parámetros sin cambiar nombres, tipos, valores predeterminados ni lógica.
- `integrations/zig-0-16-skill-section.md`: sección lista para que el coordinador la incorpore a la skill `zig-0-16`, con ejemplos MCP directos y vía `hub_execute`.
- `tests/test_mcp_descriptions.py`: fija los disparadores textuales y la forma de los parámetros anunciados.

## Cómo medir

Usa `scripts/usage_sessions.py` para comparar sesiones Zig 0.16 antes y después de integrar estos textos. Cuenta una sesión como **espontánea** si el agente consulta pyzig antes de que el usuario lo pida; como **pedida** si la primera consulta ocurre después de una solicitud explícita. Registra también el momento: antes del portado, ante una API de 0.16 o después de un error de compilación.

Compara la proporción de sesiones Zig relevantes con consulta espontánea y la proporción con consulta pedida en ambos periodos, usando el mismo criterio de inclusión y clasificación. Reporta conteos y denominadores junto a las proporciones. La medición posterior y cualquier mejora quedan `NOT_DEMONSTRATED` hasta que se ejecute el análisis; no hay cifras de uso incluidas aquí.
