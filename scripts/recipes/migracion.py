"""Recetas de MIGRACION Zig 0.13/0.14 -> 0.16.0 (operation_id `zig0.16/migrate-*`).

`py_ref` guarda aqui el codigo Zig VIEJO (el que ya no compila en 0.16);
`source_lang` es "zig-0.13/0.14" para dejarlo claro. `error_signatures` son
lineas `error: ...` REALES copiadas de compilar ese codigo viejo con
zig 0.16.0 (sin ruta ni posicion). Cada zig_test se verifica con `zig test`."""
from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"; PY = "3.12"; PROV = "std local de zig 0.16.0 (repo en lib/std); errores copiados de `zig test` 0.16.0"
SRC = "zig-0.13/0.14"
HDR = 'const std = @import("std");\n\n'
_SKIP = dict(type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
             skip_reason="migracion de API: sin driver diferencial")


def entry(oid, name, intent, aliases, old, impl, tests, apis, constraints, differences,
          sigs, side_effects=None, error_behavior="", ownership=""):
    return dict(
        operation_id=oid, name=name, intent=intent, aliases=aliases,
        source_lang=SRC, target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=old, zig_impl=impl, zig_test=HDR + impl + "\n\n" + tests,
        apis_used=apis, constraints=constraints, differences=differences,
        error_signatures=sigs, side_effects=side_effects or [],
        error_behavior=error_behavior, ownership_memory=ownership, provenance=PROV)


ENTRIES = []

# ---------------------------------------------------------------- readFileAlloc
ENTRIES.append(entry(
    "zig0.16/migrate-readfilealloc",
    "migrar std.fs.cwd().readFileAlloc a std.Io.Dir",
    "Leer un archivo completo a memoria en Zig 0.16: std.fs.cwd() ya no existe; el directorio vive en std.Io.Dir, toda operacion recibe `io` y el limite es un std.Io.Limit.",
    ["std.fs.cwd", "readFileAlloc", "std.fs", "migrar 0.14 a 0.16", "migracion zig", "leer archivo entero", "fs.cwd removed", "Io.Dir.cwd", "max_bytes", "Limit.limited"],
    '''// Zig 0.13/0.14 (NO compila en 0.16)
const std = @import("std");
pub fn leer(gpa: std.mem.Allocator, path: []const u8) ![]u8 {
    return std.fs.cwd().readFileAlloc(gpa, path, 1024 * 1024);
}''',
    '''pub fn leer(io: std.Io, dir: std.Io.Dir, gpa: std.mem.Allocator, path: []const u8) ![]u8 {
    // orden 0.16: (io, sub_path, gpa, limit); con std.Io.Dir.cwd() se lee relativo al cwd
    return dir.readFileAlloc(io, path, gpa, .limited(1024 * 1024));
}''',
    '''test "lee el contenido completo" {
    const io = std.testing.io;
    const gpa = std.testing.allocator;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "datos.txt", .data = "hola\\nmundo\\n" });
    const data = try leer(io, tmp.dir, gpa, "datos.txt");
    defer gpa.free(data);
    try std.testing.expectEqualStrings("hola\\nmundo\\n", data);
}

test "archivo ausente da FileNotFound" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try std.testing.expectError(error.FileNotFound, leer(io, tmp.dir, std.testing.allocator, "no_existe.txt"));
}

test "el limite devuelve StreamTooLong" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "g.txt", .data = "0123456789" });
    try std.testing.expectError(error.StreamTooLong, tmp.dir.readFileAlloc(io, "g.txt", std.testing.allocator, .limited(4)));
}

test "std.Io.Dir.cwd existe y es el punto de entrada" {
    _ = std.Io.Dir.cwd();
}''',
    ["std.Io.Dir.readFileAlloc", "std.Io.Dir.cwd", "std.Io.Limit.limited", "std.Io.Dir.writeFile", "std.testing.io", "std.testing.tmpDir"],
    ["el `io` se obtiene de `std.process.Init` en main (init.io) o de std.testing.io en tests",
     "el limite se pasa como std.Io.Limit (.limited(n) / .unlimited), no como usize"],
    ["0.14: std.fs.cwd().readFileAlloc(gpa, path, max_bytes); 0.16: std.Io.Dir.cwd().readFileAlloc(io, path, gpa, .limited(n))",
     "cambia el orden de argumentos: io y ruta primero, el allocator despues",
     "al exceder el limite el error es error.StreamTooLong"],
    ["error: root source file struct 'fs' has no member named 'cwd'",
     "error: member function expected 4 argument(s), found 3"],
    side_effects=["lee del sistema de archivos"],
    error_behavior="FileNotFound si no existe; StreamTooLong si supera el limite",
    ownership="el llamador libera el slice devuelto con gpa.free"))

# ---------------------------------------------------------------- writeFile
ENTRIES.append(entry(
    "zig0.16/migrate-writefile",
    "migrar std.fs.cwd().writeFile a std.Io.Dir.writeFile",
    "Escribir un archivo de una sola vez en Zig 0.16: cwd().writeFile(.{sub_path,data}) pasa a Dir.writeFile(io, .{...}) sobre std.Io.Dir.",
    ["std.fs.cwd().writeFile", "writeFile", "escribir archivo", "createFile y write", "migrar fs a Io.Dir", "guardar texto en archivo", "write whole file"],
    '''// Zig 0.14 (NO compila en 0.16)
const std = @import("std");
pub fn guardar(path: []const u8, data: []const u8) !void {
    try std.fs.cwd().writeFile(.{ .sub_path = path, .data = data });
}''',
    '''pub fn guardar(io: std.Io, dir: std.Io.Dir, path: []const u8, data: []const u8) !void {
    try dir.writeFile(io, .{ .sub_path = path, .data = data });
}''',
    '''test "escribe y relee" {
    const io = std.testing.io;
    const gpa = std.testing.allocator;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try guardar(io, tmp.dir, "s.txt", "uno");
    const a = try tmp.dir.readFileAlloc(io, "s.txt", gpa, .limited(64));
    defer gpa.free(a);
    try std.testing.expectEqualStrings("uno", a);
}

test "sobrescribe (trunca) por defecto" {
    const io = std.testing.io;
    const gpa = std.testing.allocator;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try guardar(io, tmp.dir, "s.txt", "largo largo");
    try guardar(io, tmp.dir, "s.txt", "x");
    const a = try tmp.dir.readFileAlloc(io, "s.txt", gpa, .limited(64));
    defer gpa.free(a);
    try std.testing.expectEqualStrings("x", a);
}

test "directorio padre ausente da FileNotFound" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try std.testing.expectError(error.FileNotFound, guardar(io, tmp.dir, "no/hay/s.txt", "x"));
}''',
    ["std.Io.Dir.writeFile", "std.Io.Dir.WriteFileOptions", "std.Io.Dir.readFileAlloc", "std.testing.tmpDir"],
    ["no crea directorios intermedios (usa createDirPath antes)"],
    ["0.14: std.fs.cwd().writeFile(.{...}); 0.16: dir.writeFile(io, .{ .sub_path, .data, .flags })",
     "WriteFileOptions.flags es CreateFileOptions (truncate por defecto)"],
    ["error: root source file struct 'fs' has no member named 'cwd'"],
    side_effects=["crea o trunca un archivo"],
    error_behavior="FileNotFound si falta el directorio padre"))

# ---------------------------------------------------------------- stdout
ENTRIES.append(entry(
    "zig0.16/migrate-stdout-writer",
    "migrar std.io.getStdOut().writer() al writer con buffer de std.Io",
    "Imprimir por stdout en Zig 0.16: std.io.getStdOut()/std.fs.File.stdout() ya no existen; se usa std.Io.File.stdout().writer(io, &buffer), se escribe por .interface y hay que hacer flush.",
    ["std.io.getStdOut", "getStdOut().writer()", "stdout print", "std.fs.File.stdout", "writer buffer flush", "imprimir en consola", "std.Io.Writer", "migrar 0.14 a 0.16", "juicy main", "std.process.Init", "print sin flush no imprime"],
    '''// Zig 0.13/0.14 (NO compila en 0.16)
const std = @import("std");
pub fn main() !void {
    const stdout = std.io.getStdOut().writer();
    try stdout.print("hola {s}\\n", .{"mundo"});
}''',
    '''pub fn saludar(w: *std.Io.Writer, quien: []const u8) !void {
    try w.print("hola {s}\\n", .{quien});
}

pub fn main(init: std.process.Init) !void {
    var buf: [1024]u8 = undefined;
    var fw: std.Io.File.Writer = std.Io.File.stdout().writer(init.io, &buf);
    try saludar(&fw.interface, "mundo");
    try fw.interface.flush(); // sin flush el buffer no sale
}''',
    '''test "saludar escribe en cualquier std.Io.Writer" {
    var buf: [64]u8 = undefined;
    var w: std.Io.Writer = .fixed(&buf);
    try saludar(&w, "mundo");
    try std.testing.expectEqualStrings("hola mundo\\n", w.buffered());
}

test "File.Writer con buffer: nada llega al archivo hasta flush" {
    const io = std.testing.io;
    const gpa = std.testing.allocator;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var file = try tmp.dir.createFile(io, "out.txt", .{});
    defer file.close(io);
    var buf: [64]u8 = undefined;
    var fw = file.writer(io, &buf);
    try saludar(&fw.interface, "x");
    const antes = try tmp.dir.readFileAlloc(io, "out.txt", gpa, .limited(64));
    defer gpa.free(antes);
    try std.testing.expectEqual(@as(usize, 0), antes.len);
    try fw.interface.flush();
    const despues = try tmp.dir.readFileAlloc(io, "out.txt", gpa, .limited(64));
    defer gpa.free(despues);
    try std.testing.expectEqualStrings("hola x\\n", despues);
}

test "main con std.process.Init compila (stdout().writer(io, &buf))" {
    _ = &main;
}''',
    ["std.Io.File.stdout", "std.Io.File.writer", "std.Io.File.Writer", "std.Io.Writer.fixed", "std.Io.Writer.flush", "std.process.Init"],
    ["main(init: std.process.Init) entrega gpa, io y arena; sin esa firma no hay `io` global",
     "el buffer debe vivir mientras viva el writer"],
    ["0.14: std.io.getStdOut().writer() sin buffer; 0.15 (tampoco existe ya): std.fs.File.stdout().writer(&buf); 0.16: std.Io.File.stdout().writer(io, &buf)",
     "se escribe con writer.interface.print(...) y es obligatorio interface.flush()",
     "las funciones auxiliares conviene que reciban *std.Io.Writer"],
    ["error: root source file struct 'std' has no member named 'io'",
     "error: root source file struct 'fs' has no member named 'File'"],
    side_effects=["escribe en stdout"],
    error_behavior="WriteFailed si el destino falla",
    ownership="el buffer es del llamador"))

# ---------------------------------------------------------------- ArrayList
ENTRIES.append(entry(
    "zig0.16/migrate-arraylist-unmanaged",
    "migrar std.ArrayList(T).init(allocator) a ArrayList sin allocator guardado",
    "En Zig 0.16 std.ArrayList(T) ya no guarda el allocator: se inicia con `.empty` y cada metodo que reserva memoria (append, deinit, toOwnedSlice...) recibe el allocator.",
    ["ArrayList init", "ArrayListUnmanaged", "ArrayList(u8).init", "list.append", "list.deinit", ".empty", "managed vs unmanaged", "migrar 0.14 a 0.16", "std.array_list.Managed", "toOwnedSlice allocator", "ArrayList(u8).init(allocator)", "init(allocator) ya no existe", "usar .empty"],
    '''// Zig 0.13/0.14 (NO compila en 0.16)
const std = @import("std");
test "lista" {
    var list = std.ArrayList(u32).init(std.testing.allocator);
    defer list.deinit();
    try list.append(7);
}''',
    '''pub fn rango(gpa: std.mem.Allocator, n: u32) ![]u32 {
    var list: std.ArrayList(u32) = .empty;
    errdefer list.deinit(gpa);
    var i: u32 = 0;
    while (i < n) : (i += 1) try list.append(gpa, i);
    return list.toOwnedSlice(gpa);
}''',
    '''test "rango construye y entrega la memoria" {
    const gpa = std.testing.allocator;
    const r = try rango(gpa, 4);
    defer gpa.free(r);
    try std.testing.expectEqualSlices(u32, &.{ 0, 1, 2, 3 }, r);
}

test "deinit recibe el allocator y no hay fugas" {
    const gpa = std.testing.allocator;
    var list: std.ArrayList(u8) = .empty;
    defer list.deinit(gpa);
    try list.appendSlice(gpa, "abc");
    try list.append(gpa, 'd');
    try std.testing.expectEqualStrings("abcd", list.items);
}

test "el viejo estilo sigue en std.array_list.Managed" {
    var list = std.array_list.Managed(u8).init(std.testing.allocator);
    defer list.deinit();
    try list.append('x');
    try std.testing.expectEqual(@as(usize, 1), list.items.len);
}''',
    ["std.ArrayList", "std.ArrayList.empty", "std.ArrayList.append", "std.ArrayList.toOwnedSlice", "std.array_list.Managed"],
    ["`.empty` no reserva memoria: es seguro como valor inicial de un campo"],
    ["0.14: ArrayList(T).init(a) guardaba el allocator; 0.16: ArrayList(T) es el antiguo ArrayListUnmanaged",
     "append/appendSlice/ensureTotalCapacity/deinit/toOwnedSlice reciben el allocator como primer argumento",
     "std.array_list.Managed conserva la API vieja pero esta marcada Deprecated"],
    ["error: struct 'array_list.Aligned(u32,null)' has no member named 'init'",
     "error: struct 'array_list.Aligned(u8,null)' has no member named 'init'",
     "error: member function expected 2 argument(s), found 1"],
    side_effects=["reserva memoria"],
    error_behavior="OutOfMemory",
    ownership="toOwnedSlice entrega el slice al llamador (gpa.free); deinit(gpa) libera la lista"))

# ---------------------------------------------------------------- @Type
ENTRIES.append(entry(
    "zig0.16/migrate-type-builtin",
    "migrar @Type(.{ .int = ... }) a los builtins @Int/@Struct de Zig 0.16",
    "@Type fue eliminado en Zig 0.16: los tipos se construyen con builtins dedicados como @Int(signedness, bits) y @Struct(layout, backing, nombres, tipos, atributos).",
    ["@Type removed", "@Type(.{ .int", "@Type eliminado", "std.builtin.Type", "crear tipo en comptime", "reification", "@Int", "@Struct", "invalid builtin function", "integer of arbitrary width"],
    '''// Zig 0.13/0.14 (NO compila en 0.16)
const std = @import("std");
test "tipo" {
    const U7 = @Type(.{ .int = .{ .signedness = .unsigned, .bits = 7 } });
    try std.testing.expectEqual(7, @bitSizeOf(U7));
}''',
    '''pub fn Entero(comptime bits: u16) type {
    return @Int(.unsigned, bits);
}

pub const Par = @Struct(.auto, null, &.{ "a", "b" }, &.{ u8, u16 }, &@splat(.{}));''',
    '''test "@Int crea enteros de ancho arbitrario" {
    try std.testing.expectEqual(@as(u16, 7), @bitSizeOf(Entero(7)));
    try std.testing.expectEqual(@as(Entero(7), 127), @as(Entero(7), std.math.maxInt(Entero(7))));
}

test "@Struct crea un struct con los campos pedidos" {
    const p: Par = .{ .a = 1, .b = 2 };
    try std.testing.expectEqual(@as(u8, 1), p.a);
    try std.testing.expectEqual(@as(u16, 2), p.b);
    try std.testing.expect(@hasField(Par, "b"));
}''',
    ["@Int", "@Struct", "@splat", "@bitSizeOf"],
    ["los builtins dependen de la version exacta: cada tipo (@Enum, @Union, @Tuple, @Pointer...) tiene el suyo; solo @Int y @Struct estan demostrados aqui"],
    ["0.14: @Type(.{ .int = ... }) con std.builtin.Type; 0.16: @Int(.unsigned, 7)",
     "NOT_DEMONSTRATED: equivalentes de @Enum/@Union/@Pointer/@Fn no probados en esta receta"],
    ["error: invalid builtin function: '@Type'"],
    error_behavior="error de compilacion si los argumentos no son comptime"))

# ---------------------------------------------------------------- Child.run
ENTRIES.append(entry(
    "zig0.16/migrate-child-run",
    "migrar std.process.Child.run a std.process.run(gpa, io, ...)",
    "Ejecutar un proceso y capturar stdout/stderr en Zig 0.16: std.process.Child.run(.{allocator,...}) pasa a std.process.run(gpa, io, .{ .argv, .stdout_limit... }).",
    ["Child.run", "std.process.Child.run", "ejecutar comando", "capturar stdout", "RunResult", "max_output_bytes", "stdout_limit", "migrar 0.14 a 0.16", "subprocess"],
    '''// Zig 0.13/0.14 (NO compila en 0.16)
const std = @import("std");
test "proceso" {
    const gpa = std.testing.allocator;
    const res = try std.process.Child.run(.{ .allocator = gpa, .argv = &.{ "printf", "hola" } });
    defer gpa.free(res.stdout);
    defer gpa.free(res.stderr);
}''',
    '''pub fn correr(gpa: std.mem.Allocator, io: std.Io, argv: []const []const u8) !std.process.RunResult {
    return std.process.run(gpa, io, .{
        .argv = argv,
        .stdout_limit = .limited(64 * 1024),
        .stderr_limit = .limited(64 * 1024),
    });
}''',
    '''test "captura stdout y exit 0" {
    const gpa = std.testing.allocator;
    const res = try correr(gpa, std.testing.io, &.{ "printf", "hola" });
    defer gpa.free(res.stdout);
    defer gpa.free(res.stderr);
    try std.testing.expect(res.term == .exited);
    try std.testing.expectEqual(@as(u8, 0), res.term.exited);
    try std.testing.expectEqualStrings("hola", res.stdout);
}

test "exit distinto de cero" {
    const gpa = std.testing.allocator;
    const res = try correr(gpa, std.testing.io, &.{ "sh", "-c", "echo boom >&2; exit 3" });
    defer gpa.free(res.stdout);
    defer gpa.free(res.stderr);
    try std.testing.expectEqual(@as(u8, 3), res.term.exited);
    try std.testing.expect(std.mem.indexOf(u8, res.stderr, "boom") != null);
}''',
    ["std.process.run", "std.process.RunResult", "std.Io.Limit.limited", "std.testing.io"],
    ["requiere un binario ejecutable en PATH (printf/sh)"],
    ["0.14: std.process.Child.run(.{ .allocator, .argv, .max_output_bytes }); 0.16: std.process.run(gpa, io, .{ .argv, .stdout_limit, .stderr_limit })",
     "el limite de salida se divide en stdout_limit/stderr_limit y es std.Io.Limit"],
    ["error: root source file struct 'process.Child' has no member named 'run'"],
    side_effects=["lanza un proceso hijo"],
    error_behavior="StreamTooLong si se supera un limite; el codigo de salida va en res.term",
    ownership="el llamador libera res.stdout y res.stderr con gpa.free"))

# ---------------------------------------------------------------- sleep
ENTRIES.append(entry(
    "zig0.16/migrate-time-sleep",
    "migrar std.time.sleep / std.Thread.sleep a std.Io.sleep",
    "Dormir un tiempo en Zig 0.16: std.time.sleep(ns) y std.Thread.sleep(ns) ya no existen; se usa std.Io.sleep(io, duration, clock).",
    ["std.time.sleep", "std.Thread.sleep", "sleep", "dormir", "esperar milisegundos", "Io.sleep", "std.Io.Duration", "fromMilliseconds", "Clock.awake", "migrar 0.14 a 0.16", "time.sleep removed"],
    '''// Zig 0.13/0.14 (NO compila en 0.16)
const std = @import("std");
test "dormir" {
    std.time.sleep(5 * std.time.ns_per_ms);
}''',
    '''pub fn dormirMs(io: std.Io, ms: i64) !void {
    try io.sleep(.fromMilliseconds(ms), .awake);
}''',
    '''test "duerme al menos lo pedido segun el reloj awake" {
    const io = std.testing.io;
    const t0 = std.Io.Clock.awake.now(io);
    try dormirMs(io, 20);
    const t1 = std.Io.Clock.awake.now(io);
    try std.testing.expect(t0.durationTo(t1).nanoseconds >= 20 * std.time.ns_per_ms);
}

test "Clock.Duration.sleep es la forma equivalente" {
    const io = std.testing.io;
    try (std.Io.Clock.Duration{ .raw = .fromMilliseconds(1), .clock = .awake }).sleep(io);
}''',
    ["std.Io.sleep", "std.Io.Duration.fromMilliseconds", "std.Io.Clock.awake", "std.Io.Clock.now", "std.Io.Clock.Duration.sleep"],
    ["devuelve error.Canceled si la tarea se cancela (es un punto de cancelacion)"],
    ["0.14: std.time.sleep(ns) / std.Thread.sleep(ns) bloqueaban el hilo; 0.16: std.Io.sleep(io, duration, clock) y depende del Io elegido",
     "Duration ya no es un entero de nanosegundos: se construye con fromMilliseconds/fromNanoseconds"],
    ["error: root source file struct 'time' has no member named 'sleep'",
     "error: root source file struct 'Thread' has no member named 'sleep'"],
    error_behavior="error.Canceled si la tarea se cancela"))

# ---------------------------------------------------------------- Mutex
ENTRIES.append(entry(
    "zig0.16/migrate-thread-mutex",
    "migrar std.Thread.Mutex a std.Io.Mutex",
    "Exclusion mutua en Zig 0.16: std.Thread.Mutex ya no existe; se usa std.Io.Mutex, cuyo lock/unlock reciben `io` (lock es cancelable; lockUncancelable no).",
    ["std.Thread.Mutex", "Mutex", "mutex lock unlock", "exclusion mutua", "Io.Mutex", "lockUncancelable", "tryLock", "seccion critica", "migrar 0.14 a 0.16", "proteger contador compartido", "threads"],
    '''// Zig 0.13/0.14 (NO compila en 0.16)
const std = @import("std");
var mutex: std.Thread.Mutex = .{};
var counter: u32 = 0;
test "mutex" {
    mutex.lock();
    defer mutex.unlock();
    counter += 1;
}''',
    '''pub const Contador = struct {
    mutex: std.Io.Mutex = .init,
    valor: u32 = 0,

    pub fn incrementar(self: *Contador, io: std.Io) void {
        self.mutex.lockUncancelable(io);
        defer self.mutex.unlock(io);
        self.valor += 1;
    }
};''',
    '''fn trabajo(c: *Contador, io: std.Io, n: u32) void {
    var i: u32 = 0;
    while (i < n) : (i += 1) c.incrementar(io);
}

test "dos hilos incrementan sin perder cuentas" {
    const io = std.testing.io;
    var c: Contador = .{};
    const t1 = try std.Thread.spawn(.{}, trabajo, .{ &c, io, 1000 });
    const t2 = try std.Thread.spawn(.{}, trabajo, .{ &c, io, 1000 });
    t1.join();
    t2.join();
    try std.testing.expectEqual(@as(u32, 2000), c.valor);
}

test "tryLock no bloquea y lock cancelable devuelve error!void" {
    const io = std.testing.io;
    var m: std.Io.Mutex = .init;
    try std.testing.expect(m.tryLock());
    try std.testing.expect(!m.tryLock());
    m.unlock(io);
    try m.lock(io);
    m.unlock(io);
}''',
    ["std.Io.Mutex", "std.Io.Mutex.init", "std.Io.Mutex.lockUncancelable", "std.Io.Mutex.tryLock", "std.Thread.spawn"],
    ["lock(io) puede fallar con Canceled: usa lockUncancelable si no quieres propagar"],
    ["0.14: var m: std.Thread.Mutex = .{}; m.lock(); m.unlock(); 0.16: std.Io.Mutex = .init; m.lock(io) / m.unlock(io)",
     "std.Thread.spawn/join siguen existiendo; lo que cambia es el tipo del mutex y que recibe io"],
    ["error: root source file struct 'Thread' has no member named 'Mutex'"],
    error_behavior="lock devuelve error.Canceled si la tarea se cancela"))


CONTRACTS = {e["operation_id"]: _c(None, None, None, [], **_SKIP) for e in ENTRIES}
