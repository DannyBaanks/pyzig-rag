## Cuándo consultar pyzig-rag

Antes de portar código Python a Zig 0.16, busca primero una receta equivalente. Consulta también antes de usar APIs que cambiaron en 0.16, especialmente `std.Io`, `ArrayList` y `build.zig`.

Si Zig 0.16 muestra un error de compilación, busca pegando el mensaje completo en `pyzig_search(intent=...)`. Para compilar el fragmento Zig y recibir recetas sugeridas para sus errores, usa `pyzig_check(zig_code=...)`.

Ejemplos de llamada:

```python
pyzig_search(intent="leer un archivo JSON con límite", py_code="data = json.load(f)")
hub_execute(server="pyzig-rag", tool="pyzig_search", arguments={
    "intent": "ArrayList y build.zig en Zig 0.16",
})
hub_execute(server="pyzig-rag", tool="pyzig_search", arguments={
    "intent": "error: member function expected 2 argument(s), found 1; std.Io",
})
```

Revisa `status` y `differences`: solo `DEMONSTRATED` es equivalencia comprobada; `NO_RESULTS` significa que no hay receta admitida.
