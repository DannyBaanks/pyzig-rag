"""Recetas de Python 3.12 -> Zig 0.16.0 para el area tiempo_args.

Cubre:
- time.time() epoch (std.Io.Clock real)
- time.monotonic() para medir duracion (std.Io.Clock awake)
- random con semilla reproducible (std.Random.DefaultPrng) y randint/choice/shuffle
- sys.argv iteracion (std.process.Args en 0.16)
- argparse minimo de flags --nombre valor
- zlib.crc32 (std.hash.Crc32)
- hashlib.md5 hexdigest (std.crypto.hash.Md5)
"""

from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"
PY = "3.12"
PROV = "std local de zig 0.16.0 (repo en lib/std)"

ENTRIES = [
    dict(
        operation_id="zig0.16/epoch-now-seconds",
        name="obtener timestamp epoch en segundos y milisegundos",
        intent="Obtener el tiempo actual del sistema (reloj de pared / UTC) como segundos o milisegundos transcurridos desde el epoch Unix (1970-01-01), equivalente a time.time() en Python.",
        aliases=[
            "time.time",
            "epoch",
            "unix timestamp",
            "reloj de pared",
            "wall clock",
            "system time",
            "timestamp actual",
            "obtener fecha hora unix",
            "std.Io.Clock.real",
            "posix epoch",
            "tiempo actual en segundos",
            "time in seconds",
        ],
        source_lang="python",
        target_lang="zig",
        zig_version=ZIG,
        python_version=PY,
        platform="linux",
        py_ref='''import time
now_s = int(time.time())
now_ms = int(time.time() * 1000)
# time.time() da segundos flotantes desde 1970-01-01 UTC''',
        zig_impl='''pub fn epochSeconds(io: std.Io) i64 {
    const ts = std.Io.Clock.real.now(io);
    return ts.toSeconds();
}

pub fn epochMillis(io: std.Io) i64 {
    const ts = std.Io.Clock.real.now(io);
    return ts.toMilliseconds();
}

pub fn epochSecondsFloat(io: std.Io) f64 {
    const ts = std.Io.Clock.real.now(io);
    return @as(f64, @floatFromInt(ts.nanoseconds)) / @as(f64, std.time.ns_per_s);
}''',
        zig_test='''const std = @import("std");

pub fn epochSeconds(io: std.Io) i64 {
    const ts = std.Io.Clock.real.now(io);
    return ts.toSeconds();
}

pub fn epochMillis(io: std.Io) i64 {
    const ts = std.Io.Clock.real.now(io);
    return ts.toMilliseconds();
}

pub fn epochSecondsFloat(io: std.Io) f64 {
    const ts = std.Io.Clock.real.now(io);
    return @as(f64, @floatFromInt(ts.nanoseconds)) / @as(f64, std.time.ns_per_s);
}

test "epoch segundos es razonable para fecha posterior a 2024" {
    const io = std.testing.io;
    const s = epochSeconds(io);
    try std.testing.expect(s > 1700000000);
}

test "epoch milisegundos es coherente con segundos" {
    const io = std.testing.io;
    const s = epochSeconds(io);
    const ms = epochMillis(io);
    try std.testing.expect(ms >= s * 1000);
    try std.testing.expect(ms < (s + 2) * 1000);
}

test "epoch flotante tiene parte decimal y conversion correcta" {
    const io = std.testing.io;
    const f = epochSecondsFloat(io);
    const s = epochSeconds(io);
    try std.testing.expect(f >= @as(f64, @floatFromInt(s)));
    try std.testing.expect(f < @as(f64, @floatFromInt(s + 2)));
}''',
        apis_used=[
            "std.Io.Clock.real.now",
            "std.Io.Timestamp.toSeconds",
            "std.Io.Timestamp.toMilliseconds",
            "std.time.ns_per_s",
        ],
        constraints=["sin root", "io inyectado"],
        preconditions=["reloj del sistema configurado"],
        postconditions=["timestamp >= 0 representando tiempo Unix UTC"],
        side_effects=[],
        error_behavior="no falla (operacion infalible en plataformas con reloj).",
        ownership_memory="sin asignacion; devuelve enteros o floats escalares.",
        differences=[
            "Python time.time() devuelve f64 en segundos, perdiendo resolucion sub-microsegundo por los 53 bits de mantisa de IEEE 754; Zig std.Io.Clock.real.now usa i96 nanosegundos exactos",
            "En Python time.time() accede al reloj global del SO; en Zig 0.16 se inyecta la instancia std.Io (permitiendo mock/determinismo en tests)",
            "Ambos relojes de pared (real) estan sujetos a saltos manuales del reloj del sistema y ajustes de NTP",
        ],
        provenance=PROV,
    ),
    dict(
        operation_id="zig0.16/monotonic-duration-measure",
        name="medir duracion y tiempo transcurrido con reloj monotono",
        intent="Tomar marcas de tiempo antes y despues de una operacion usando un reloj monotono inmune a cambios de hora del sistema, para medir duraciones y benchmarks con precision.",
        aliases=[
            "time.monotonic",
            "time.monotonic_ns",
            "time.perf_counter",
            "medir duracion",
            "elapsed time",
            "tiempo transcurrido",
            "benchmark duration",
            "timer",
            "cronometro",
            "clock monotonic",
            "medir tiempo de ejecucion",
            "duration measure",
            "cuanto tarda una funcion",
            "inmune al cambio de hora",
        ],
        source_lang="python",
        target_lang="zig",
        zig_version=ZIG,
        python_version=PY,
        platform="linux",
        py_ref='''import time
t0 = time.monotonic()
time.sleep(0.01)
elapsed = time.monotonic() - t0
assert elapsed >= 0.005''',
        zig_impl='''pub const Timer = struct {
    start_ts: std.Io.Timestamp,

    pub fn start(io: std.Io) Timer {
        return .{ .start_ts = std.Io.Clock.awake.now(io) };
    }

    pub fn readDuration(self: Timer, io: std.Io) std.Io.Duration {
        const now_ts = std.Io.Clock.awake.now(io);
        return self.start_ts.durationTo(now_ts);
    }

    pub fn readMillis(self: Timer, io: std.Io) i64 {
        return self.readDuration(io).toMilliseconds();
    }

    pub fn readSeconds(self: Timer, io: std.Io) f64 {
        const dur = self.readDuration(io);
        return @as(f64, @floatFromInt(dur.nanoseconds)) / @as(f64, std.time.ns_per_s);
    }
};

pub fn measureElapsed(io: std.Io, t0: std.Io.Timestamp) std.Io.Duration {
    const t1 = std.Io.Clock.awake.now(io);
    return t0.durationTo(t1);
}''',
        zig_test='''const std = @import("std");

pub const Timer = struct {
    start_ts: std.Io.Timestamp,

    pub fn start(io: std.Io) Timer {
        return .{ .start_ts = std.Io.Clock.awake.now(io) };
    }

    pub fn readDuration(self: Timer, io: std.Io) std.Io.Duration {
        const now_ts = std.Io.Clock.awake.now(io);
        return self.start_ts.durationTo(now_ts);
    }

    pub fn readMillis(self: Timer, io: std.Io) i64 {
        return self.readDuration(io).toMilliseconds();
    }

    pub fn readSeconds(self: Timer, io: std.Io) f64 {
        const dur = self.readDuration(io);
        return @as(f64, @floatFromInt(dur.nanoseconds)) / @as(f64, std.time.ns_per_s);
    }
};

pub fn measureElapsed(io: std.Io, t0: std.Io.Timestamp) std.Io.Duration {
    const t1 = std.Io.Clock.awake.now(io);
    return t0.durationTo(t1);
}

test "timer mide una pausa corta de forma monotona" {
    const io = std.testing.io;
    const t = Timer.start(io);
    try std.Io.sleep(io, .fromMilliseconds(10), .awake);
    const dur = t.readDuration(io);
    try std.testing.expect(dur.nanoseconds >= 0);
    try std.testing.expect(t.readMillis(io) >= 5);
    try std.testing.expect(t.readSeconds(io) >= 0.005);
}

test "medicion directa con marcas de tiempo consecutivas nunca retrocede" {
    const io = std.testing.io;
    const t0 = std.Io.Clock.awake.now(io);
    const dur = measureElapsed(io, t0);
    try std.testing.expect(dur.nanoseconds >= 0);
}''',
        apis_used=[
            "std.Io.Clock.awake.now",
            "std.Io.Timestamp.durationTo",
            "std.Io.Duration.toMilliseconds",
            "std.Io.sleep",
        ],
        constraints=["sin root", "io inyectado"],
        preconditions=["reloj de hardware funcional"],
        postconditions=["duracion >= 0 nanosegundos (garantia monotona)"],
        side_effects=[],
        error_behavior="no falla; la lectura es total.",
        ownership_memory="sin asignacion; devuelve structs de valor en la pila.",
        differences=[
            "En Python time.monotonic() devuelve float en segundos; en Zig std.Io.Clock.awake usa enteros i96 de nanosegundos envueltos en std.Io.Duration",
            "En Linux std.Io.Clock.awake mapea a CLOCK_MONOTONIC (no avanza durante suspension del sistema); si se requiere incluir suspension se usa std.Io.Clock.boot (CLOCK_BOOTTIME)",
            "No se producen errores de redondeo de punto flotante al acumular o restar duraciones exactas",
        ],
        provenance=PROV,
    ),
    dict(
        operation_id="zig0.16/random-prng-ops",
        name="generador pseudoaleatorio reproducible, enteros en rango, choice y shuffle",
        intent="Inicializar una PRNG con semilla fija para reproducibilidad, generar enteros en un rango cerrado [a, b], seleccionar elementos aleatorios de una coleccion y mezclar (shuffle) un slice en su lugar.",
        aliases=[
            "random.seed",
            "random.randint",
            "random.choice",
            "random.shuffle",
            "std.Random.DefaultPrng",
            "generador pseudoaleatorio",
            "semilla reproducible",
            "barajar array",
            "elegir elemento aleatorio",
            "random integer range",
            "Xoshiro256",
            "numero aleatorio",
        ],
        source_lang="python",
        target_lang="zig",
        zig_version=ZIG,
        python_version=PY,
        platform="linux",
        py_ref='''import random
random.seed(42)
n = random.randint(1, 10) # inclusivo [1, 10]
item = random.choice(["alfa", "beta", "gamma"])
arr = [1, 2, 3, 4, 5]
random.shuffle(arr)''',
        zig_impl='''pub fn initPrng(seed: u64) std.Random.DefaultPrng {
    return std.Random.DefaultPrng.init(seed);
}

pub fn randIntInclusive(rand: std.Random, comptime T: type, at_least: T, at_most: T) T {
    return rand.intRangeAtMost(T, at_least, at_most);
}

pub fn choice(rand: std.Random, comptime T: type, items: []const T) ?T {
    if (items.len == 0) return null;
    const idx = rand.uintLessThan(usize, items.len);
    return items[idx];
}

pub fn shuffle(rand: std.Random, comptime T: type, items: []T) void {
    rand.shuffle(T, items);
}''',
        zig_test='''const std = @import("std");

pub fn initPrng(seed: u64) std.Random.DefaultPrng {
    return std.Random.DefaultPrng.init(seed);
}

pub fn randIntInclusive(rand: std.Random, comptime T: type, at_least: T, at_most: T) T {
    return rand.intRangeAtMost(T, at_least, at_most);
}

pub fn choice(rand: std.Random, comptime T: type, items: []const T) ?T {
    if (items.len == 0) return null;
    const idx = rand.uintLessThan(usize, items.len);
    return items[idx];
}

pub fn shuffle(rand: std.Random, comptime T: type, items: []T) void {
    rand.shuffle(T, items);
}

test "misma semilla produce exactamente la misma secuencia (reproducibilidad)" {
    var prng1 = initPrng(12345);
    var prng2 = initPrng(12345);
    const r1 = prng1.random();
    const r2 = prng2.random();

    for (0..10) |_| {
        try std.testing.expectEqual(
            randIntInclusive(r1, i32, -50, 50),
            randIntInclusive(r2, i32, -50, 50),
        );
    }
}

test "randIntInclusive respeta limites inferior y superior" {
    var prng = initPrng(999);
    const r = prng.random();
    for (0..100) |_| {
        const val = randIntInclusive(r, i32, 1, 6);
        try std.testing.expect(val >= 1 and val <= 6);
    }
}

test "choice selecciona elemento existente y retorna null en slice vacio" {
    var prng = initPrng(777);
    const r = prng.random();
    const items = [_][]const u8{ "rojo", "verde", "azul" };
    const picked = choice(r, []const u8, &items);
    try std.testing.expect(picked != null);
    const empty: []const []const u8 = &.{};
    try std.testing.expect(choice(r, []const u8, empty) == null);
}

test "shuffle altera orden conservando todos los elementos" {
    var prng = initPrng(2026);
    const r = prng.random();
    var numbers = [_]i32{ 10, 20, 30, 40, 50, 60, 70, 80 };
    const orig = numbers;
    shuffle(r, i32, &numbers);
    try std.testing.expect(!std.mem.eql(i32, &orig, &numbers));
    var sorted = numbers;
    std.mem.sort(i32, &sorted, {}, std.sort.asc(i32));
    try std.testing.expectEqualSlices(i32, &orig, &sorted);
}''',
        apis_used=[
            "std.Random.DefaultPrng.init",
            "std.Random.DefaultPrng.random",
            "std.Random.intRangeAtMost",
            "std.Random.uintLessThan",
            "std.Random.shuffle",
        ],
        constraints=["sin root"],
        preconditions=["semilla u64 para la PRNG"],
        postconditions=["valores pseudoaleatorios reproducibles segun semilla"],
        side_effects=["modifica el estado interno del PRNG y transmuta el slice en shuffle"],
        error_behavior="choice devuelve null en slice vacio; randIntInclusive exige at_least <= at_most (assert: panic en Debug/ReleaseSafe, UB en ReleaseFast); el resto es infalible.",
        ownership_memory="shuffle modifica el slice prestado in-place; sin asignaciones en heap.",
        differences=[
            "random.randint(b, a) con b > a lanza ValueError; en Zig intRangeAtMost con a > b es un assert (panic), no un error capturable",
            "El modulo random de Python usa Mersenne Twister (MT19937, estado de 19937 bits); Zig std.Random.DefaultPrng usa Xoshiro256 (estado de 256 bits). Para la misma semilla numerica NO generan la misma secuencia de numeros",
            "Python random.seed() admite int arbitrario, float, str o bytes; en Zig init toma exclusivamente un entero u64",
            "Python random.choice([]) lanza IndexError; aqui devuelve null (?T)",
            "Para usos criptograficos ninguno de los dos es apto: en Zig debe usarse std.crypto.random",
        ],
        provenance=PROV,
    ),
    dict(
        operation_id="zig0.16/process-args-iterate",
        name="iterar y recolectar argumentos de linea de comandos",
        intent="Acceder a los argumentos pasados al ejecutable (sys.argv), recorrerlos secuencialmente con std.process.Args y convertirlos en un slice de cadenas sin fugas de memoria.",
        aliases=[
            "sys.argv",
            "argumentos linea comandos",
            "command line arguments",
            "std.process.Args",
            "iterar argv",
            "args.iterate",
            "argv iterator",
            "leer argumentos programa",
            "parametros de consola",
            "cli args iteration",
        ],
        source_lang="python",
        target_lang="zig",
        zig_version=ZIG,
        python_version=PY,
        platform="linux",
        py_ref='''import sys
prog = sys.argv[0]
for arg in sys.argv[1:]:
    pass
all_args = list(sys.argv)''',
        zig_impl='''pub fn countArgs(args: std.process.Args) usize {
    var it = args.iterate();
    defer it.deinit();
    var count: usize = 0;
    while (it.next()) |_| {
        count += 1;
    }
    return count;
}

pub fn collectArgsSlice(args: std.process.Args, arena: std.mem.Allocator) ![]const [:0]const u8 {
    return args.toSlice(arena);
}

pub fn getFirstArg(args: std.process.Args) ?[:0]const u8 {
    var it = args.iterate();
    defer it.deinit();
    return it.next();
}''',
        zig_test='''const std = @import("std");

pub fn countArgs(args: std.process.Args) usize {
    var it = args.iterate();
    defer it.deinit();
    var count: usize = 0;
    while (it.next()) |_| {
        count += 1;
    }
    return count;
}

pub fn collectArgsSlice(args: std.process.Args, arena: std.mem.Allocator) ![]const [:0]const u8 {
    return args.toSlice(arena);
}

pub fn getFirstArg(args: std.process.Args) ?[:0]const u8 {
    var it = args.iterate();
    defer it.deinit();
    return it.next();
}

test "iteracion con Args.iterate cuenta correctamente" {
    const raw = [_][*:0]const u8{ "binario", "--verbose", "entrada.txt" };
    const args: std.process.Args = .{ .vector = &raw };
    try std.testing.expectEqual(@as(usize, 3), countArgs(args));
}

test "getFirstArg devuelve el primer elemento o null si vacio" {
    const raw = [_][*:0]const u8{"mi_programa"};
    const args: std.process.Args = .{ .vector = &raw };
    try std.testing.expectEqualStrings("mi_programa", getFirstArg(args).?);

    const empty_raw = [_][*:0]const u8{};
    const empty_args: std.process.Args = .{ .vector = &empty_raw };
    try std.testing.expect(getFirstArg(empty_args) == null);
}

test "collectArgsSlice recolecta todas las cadenas en arena" {
    const raw = [_][*:0]const u8{ "cmd", "-o", "salida.bin" };
    const args: std.process.Args = .{ .vector = &raw };
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();

    const slice = try collectArgsSlice(args, arena.allocator());
    try std.testing.expectEqual(@as(usize, 3), slice.len);
    try std.testing.expectEqualStrings("cmd", slice[0]);
    try std.testing.expectEqualStrings("-o", slice[1]);
    try std.testing.expectEqualStrings("salida.bin", slice[2]);
}

test "skip salta el nombre del binario e itera los restantes" {
    const raw = [_][*:0]const u8{ "cmd", "arg1", "arg2" };
    const args: std.process.Args = .{ .vector = &raw };
    var it = args.iterate();
    defer it.deinit();

    try std.testing.expect(it.skip());
    const a1 = it.next();
    try std.testing.expectEqualStrings("arg1", a1.?);
    const a2 = it.next();
    try std.testing.expectEqualStrings("arg2", a2.?);
    try std.testing.expect(it.next() == null);
}''',
        apis_used=[
            "std.process.Args.iterate",
            "std.process.Args.Iterator.next",
            "std.process.Args.Iterator.skip",
            "std.process.Args.toSlice",
        ],
        constraints=["sin root"],
        preconditions=["instancia std.process.Args obtenida en init o vector"],
        postconditions=["slices [:0]const u8 validos"],
        side_effects=[],
        error_behavior="iterate y next no fallan; toSlice propaga OutOfMemory.",
        ownership_memory="iterate() en Linux no asigna en heap (apunta a memoria de proceso); toSlice requiere un asignador.",
        differences=[
            "Python expone sys.argv globalmente como list[str]; en Zig 0.16 los argumentos se reciben a traves del parametro de entrada de main (std.process.Init.Minimal.args o std.process.Init.args)",
            "En Linux la iteracion con args.iterate() no realiza ninguna asignacion en heap (slices apuntan al bloque de argv de la pila ELF); en Python sys.argv ya realizo N asignaciones al iniciar",
            "Python decodifica con codificacion del sistema de archivos; Zig entrega bytes crudos [:0]const u8 sin asumir codificacion UTF-8",
        ],
        provenance=PROV,
    ),
    dict(
        operation_id="zig0.16/argparse-flags-parse",
        name="parsear flags de linea de comandos clave y valor",
        intent="Parsear banderas de linea de comandos estilo '--nombre valor' (y opciones booleanas) desde un iterador o slice de argumentos, asignandolas a una estructura tipada y reportando errores de banderas faltantes, valores ausentes o tipos invalidos.",
        aliases=[
            "argparse",
            "parse_args",
            "add_argument",
            "flags parser",
            "opciones linea de comandos",
            "cli flags",
            "parsear argumentos",
            "--flag value",
            "command line options",
            "parse command line arguments",
            "analizar parametros",
            "parametros de consola",
            "opciones con guion doble",
        ],
        source_lang="python",
        target_lang="zig",
        zig_version=ZIG,
        python_version=PY,
        platform="linux",
        py_ref='''import argparse
p = argparse.ArgumentParser()
p.add_argument("--host", default="127.0.0.1")
p.add_argument("--port", type=int, default=8080)
p.add_argument("--verbose", "-v", action="store_true")
args = p.parse_args(["--host", "0.0.0.0", "--port", "9000", "--verbose"])
# args.host == "0.0.0.0", args.port == 9000, args.verbose == True''',
        zig_impl='''pub const Config = struct {
    host: []const u8 = "127.0.0.1",
    port: u16 = 8080,
    verbose: bool = false,
};

pub const ParseError = error{
    MissingValue,
    InvalidNumber,
    UnknownFlag,
};

pub fn parseFlags(args: []const []const u8) ParseError!Config {
    var cfg: Config = .{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--host")) {
            i += 1;
            if (i >= args.len) return error.MissingValue;
            cfg.host = args[i];
        } else if (std.mem.eql(u8, arg, "--port")) {
            i += 1;
            if (i >= args.len) return error.MissingValue;
            cfg.port = std.fmt.parseInt(u16, args[i], 10) catch return error.InvalidNumber;
        } else if (std.mem.eql(u8, arg, "--verbose") or std.mem.eql(u8, arg, "-v")) {
            cfg.verbose = true;
        } else {
            return error.UnknownFlag;
        }
    }
    return cfg;
}''',
        zig_test='''const std = @import("std");

pub const Config = struct {
    host: []const u8 = "127.0.0.1",
    port: u16 = 8080,
    verbose: bool = false,
};

pub const ParseError = error{
    MissingValue,
    InvalidNumber,
    UnknownFlag,
};

pub fn parseFlags(args: []const []const u8) ParseError!Config {
    var cfg: Config = .{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--host")) {
            i += 1;
            if (i >= args.len) return error.MissingValue;
            cfg.host = args[i];
        } else if (std.mem.eql(u8, arg, "--port")) {
            i += 1;
            if (i >= args.len) return error.MissingValue;
            cfg.port = std.fmt.parseInt(u16, args[i], 10) catch return error.InvalidNumber;
        } else if (std.mem.eql(u8, arg, "--verbose") or std.mem.eql(u8, arg, "-v")) {
            cfg.verbose = true;
        } else {
            return error.UnknownFlag;
        }
    }
    return cfg;
}

test "valores por defecto sin argumentos" {
    const cfg = try parseFlags(&.{});
    try std.testing.expectEqualStrings("127.0.0.1", cfg.host);
    try std.testing.expectEqual(@as(u16, 8080), cfg.port);
    try std.testing.expect(!cfg.verbose);
}

test "sobrescribe host port y flag booleana" {
    const args = [_][]const u8{ "--host", "0.0.0.0", "--port", "9090", "--verbose" };
    const cfg = try parseFlags(&args);
    try std.testing.expectEqualStrings("0.0.0.0", cfg.host);
    try std.testing.expectEqual(@as(u16, 9090), cfg.port);
    try std.testing.expect(cfg.verbose);
}

test "flag corta -v activa verbose" {
    const args = [_][]const u8{"-v"};
    const cfg = try parseFlags(&args);
    try std.testing.expect(cfg.verbose);
}

test "flag con valor ausente al final retorna MissingValue" {
    const args = [_][]const u8{ "--host", "10.0.0.1", "--port" };
    try std.testing.expectError(error.MissingValue, parseFlags(&args));
}

test "puerto no numerico retorna InvalidNumber" {
    const args = [_][]const u8{ "--port", "invalido" };
    try std.testing.expectError(error.InvalidNumber, parseFlags(&args));
}

test "puerto fuera de rango u16 retorna InvalidNumber" {
    const args = [_][]const u8{ "--port", "70000" };
    try std.testing.expectError(error.InvalidNumber, parseFlags(&args));
}

test "flag desconocida retorna UnknownFlag" {
    const args = [_][]const u8{ "--no-existe", "123" };
    try std.testing.expectError(error.UnknownFlag, parseFlags(&args));
}''',
        apis_used=[
            "std.mem.eql",
            "std.fmt.parseInt",
        ],
        constraints=["sin root"],
        preconditions=["slice de argumentos de consola"],
        postconditions=["struct Config tipada con defaults"],
        side_effects=[],
        error_behavior="retorna error.MissingValue si la bandera no tiene parametro, error.InvalidNumber en parseo numerico, error.UnknownFlag ante banderas desconocidas.",
        ownership_memory="sin asignaciones; los slices de cadenas son prestados de la entrada.",
        differences=[
            "Python argparse imprime ayuda con --help, maneja abreviaciones y sale con sys.exit(2) ante errores; en Zig se retorna un error tipado explicito sin efectos secundarios",
            "No utiliza reflexion ni diccionarios dinamicos: deserializa directamente en un struct fuertemente tipado",
            "Zero allocation: las cadenas resultantes apuntan a los slices de argv sin clonar memoria",
        ],
        provenance=PROV,
    ),
    dict(
        operation_id="zig0.16/crc32-checksum",
        name="calcular checksum crc32 de bytes y en streaming",
        intent="Calcular la suma de comprobacion CRC-32 (polinomio IEEE 802.3 / ISO 3309) de un bloque de bytes de una sola vez o de forma incremental (streaming) por trozos, identico a zlib.crc32.",
        aliases=[
            "zlib.crc32",
            "crc32",
            "checksum",
            "std.hash.Crc32",
            "suma de verificacion",
            "cyclic redundancy check",
            "crc32 stream",
            "crc32 incremental",
            "integridad crc",
            "crc32 hash",
        ],
        source_lang="python",
        target_lang="zig",
        zig_version=ZIG,
        python_version=PY,
        platform="linux",
        py_ref='''import zlib
c1 = zlib.crc32(b"hello world")
c2 = zlib.crc32(b"hello ")
c2 = zlib.crc32(b"world", c2)
assert c1 == c2 == 222957957''',
        zig_impl='''pub fn crc32(data: []const u8) u32 {
    return std.hash.Crc32.hash(data);
}

pub fn crc32Streaming(chunks: []const []const u8) u32 {
    var hasher = std.hash.Crc32.init();
    for (chunks) |chunk| {
        hasher.update(chunk);
    }
    return hasher.final();
}''',
        zig_test='''const std = @import("std");

pub fn crc32(data: []const u8) u32 {
    return std.hash.Crc32.hash(data);
}

pub fn crc32Streaming(chunks: []const []const u8) u32 {
    var hasher = std.hash.Crc32.init();
    for (chunks) |chunk| {
        hasher.update(chunk);
    }
    return hasher.final();
}

test "crc32 de hello world coincide exactamente con zlib.crc32 de python" {
    const val = crc32("hello world");
    try std.testing.expectEqual(@as(u32, 222957957), val);
}

test "crc32 en streaming por trozos coincide con calculo de un solo paso" {
    const chunks = [_][]const u8{ "hello ", "world" };
    const streamed = crc32Streaming(&chunks);
    try std.testing.expectEqual(@as(u32, 222957957), streamed);
}

test "crc32 de cadena vacia es 0" {
    try std.testing.expectEqual(@as(u32, 0), crc32(""));
    try std.testing.expectEqual(@as(u32, 0), crc32Streaming(&.{}));
}

test "crc32 de datos binarios arbitrarios" {
    const bin = [_]u8{ 0x00, 0xff, 0xaa, 0x55 };
    const c = crc32(&bin);
    try std.testing.expect(c != 0);
}''',
        apis_used=[
            "std.hash.Crc32.hash",
            "std.hash.Crc32.init",
            "std.hash.Crc32.update",
            "std.hash.Crc32.final",
        ],
        constraints=["sin root"],
        preconditions=["buffer de bytes en memoria"],
        postconditions=["checksum entero sin signo u32"],
        side_effects=[],
        error_behavior="funcion total (no falla).",
        ownership_memory="sin asignacion; opera sobre slices prestados.",
        differences=[
            "En Python zlib.crc32 devuelve un entero int en [0, 2^32-1]; en Zig devuelve u32 nativo",
            "En Python la continuacion de streaming pasa el valor acumulado como segundo argumento a zlib.crc32(data, prev); en Zig se usa el struct con estado hasher.update() y hasher.final()",
            "Ambas implementaciones usan el polinomio estandar IEEE 802.3 / ISO 3309 (0x04C11DB7, reflejado 0xEDB88320)",
        ],
        provenance=PROV,
    ),
    dict(
        operation_id="zig0.16/md5-hexdigest",
        name="calcular hash md5 en bytes y representacion hexadecimal",
        intent="Calcular el hash criptografico/integridad MD5 de un buffer de bytes, obteniendo tanto el digest binario de 16 bytes como la cadena hexadecimal en minusculas de 32 caracteres (equivalente a hexdigest()).",
        aliases=[
            "hashlib.md5",
            "md5",
            "md5sum",
            "hexdigest",
            "digest md5",
            "std.crypto.hash.Md5",
            "checksum md5",
            "hash md5 hexadecimal",
            "md5 hash bytes",
            "fingerprint md5",
        ],
        source_lang="python",
        target_lang="zig",
        zig_version=ZIG,
        python_version=PY,
        platform="linux",
        py_ref='''import hashlib
h = hashlib.md5(b"hello world")
raw_bytes = h.digest()
hex_str = h.hexdigest()
assert hex_str == "5eb63bbbe01eeed093cb22bb8f5acdc3"''',
        zig_impl='''pub fn md5Bytes(data: []const u8) [16]u8 {
    return std.crypto.hash.Md5.hashResult(data);
}

pub fn md5Hex(data: []const u8) [32]u8 {
    const digest = md5Bytes(data);
    return std.fmt.bytesToHex(digest, .lower);
}

pub fn md5StreamingHex(chunks: []const []const u8) [32]u8 {
    var hasher = std.crypto.hash.Md5.init(.{});
    for (chunks) |chunk| {
        hasher.update(chunk);
    }
    var digest: [16]u8 = undefined;
    hasher.final(&digest);
    return std.fmt.bytesToHex(digest, .lower);
}''',
        zig_test='''const std = @import("std");

pub fn md5Bytes(data: []const u8) [16]u8 {
    return std.crypto.hash.Md5.hashResult(data);
}

pub fn md5Hex(data: []const u8) [32]u8 {
    const digest = md5Bytes(data);
    return std.fmt.bytesToHex(digest, .lower);
}

pub fn md5StreamingHex(chunks: []const []const u8) [32]u8 {
    var hasher = std.crypto.hash.Md5.init(.{});
    for (chunks) |chunk| {
        hasher.update(chunk);
    }
    var digest: [16]u8 = undefined;
    hasher.final(&digest);
    return std.fmt.bytesToHex(digest, .lower);
}

test "md5 de hello world coincide con hexdigest de Python" {
    try std.testing.expectEqualStrings("5eb63bbbe01eeed093cb22bb8f5acdc3", &md5Hex("hello world"));
}

test "md5 de cadena vacia coincide con vector estandar" {
    try std.testing.expectEqualStrings("d41d8cd98f00b204e9800998ecf8427e", &md5Hex(""));
}

test "md5 streaming produce el mismo resultado que un solo paso" {
    const chunks = [_][]const u8{ "hel", "lo ", "world" };
    try std.testing.expectEqualStrings(&md5Hex("hello world"), &md5StreamingHex(&chunks));
}

test "md5Bytes devuelve 16 bytes crudos" {
    const raw = md5Bytes("abc");
    try std.testing.expectEqual(@as(usize, 16), raw.len);
    const hex = std.fmt.bytesToHex(raw, .lower);
    try std.testing.expectEqualStrings("900150983cd24fb0d6963f7d28e17f72", &hex);
}''',
        apis_used=[
            "std.crypto.hash.Md5.hashResult",
            "std.crypto.hash.Md5.init",
            "std.crypto.hash.Md5.update",
            "std.crypto.hash.Md5.final",
            "std.fmt.bytesToHex",
        ],
        constraints=["sin root"],
        preconditions=["buffer de bytes en memoria"],
        postconditions=["digest [16]u8 o cadena hex [32]u8 en minusculas"],
        side_effects=[],
        error_behavior="funcion total (no falla).",
        ownership_memory="devuelve arrays de longitud fija en la pila ([16]u8, [32]u8) sin heap.",
        differences=[
            "Python hashlib.md5(b'...').hexdigest() devuelve un objeto str de 32 caracteres; Zig devuelve un array de longitud fija [32]u8 de pila sin asignacion dinamica",
            "Python hashlib.md5 puede estar sujeto a restricciones FIPS en el sistema operativo; la std de Zig compila la implementacion pura de MD5 de forma independiente",
            "MD5 no es criptograficamente seguro contra colisiones; para integridad criptografica actual debe usarse SHA-256 o BLAKE3",
        ],
        provenance=PROV,
    ),
]

CONTRACTS = {
    "zig0.16/epoch-now-seconds": _c(
        None,
        None,
        None,
        [],
        type_sig={"input": "void", "output": "int"},
        skip_reason="sin driver diferencial todavia",
    ),
    "zig0.16/monotonic-duration-measure": _c(
        None,
        None,
        None,
        [],
        type_sig={"input": "duration", "output": "duration"},
        skip_reason="sin driver diferencial todavia",
    ),
    "zig0.16/random-prng-ops": _c(
        None,
        None,
        None,
        [],
        type_sig={"input": "seed", "output": "int"},
        skip_reason="sin driver diferencial todavia",
    ),
    "zig0.16/process-args-iterate": _c(
        None,
        None,
        None,
        [],
        type_sig={"input": "argv", "output": "argv"},
        skip_reason="sin driver diferencial todavia",
    ),
    "zig0.16/argparse-flags-parse": _c(
        None,
        None,
        None,
        [],
        type_sig={"input": "argv", "output": "config"},
        skip_reason="sin driver diferencial todavia",
    ),
    "zig0.16/crc32-checksum": _c(
        None,
        None,
        None,
        [],
        type_sig={"input": "bytes", "output": "int"},
        skip_reason="sin driver diferencial todavia",
    ),
    "zig0.16/md5-hexdigest": _c(
        None,
        None,
        None,
        [],
        type_sig={"input": "bytes", "output": "hex"},
        skip_reason="sin driver diferencial todavia",
    ),
}
