"""Recetas enfocadas en APIs de Zig 0.16 que aun no estaban cubiertas como tarea.

Incluye una firma real nueva de comptilacion y ejemplos demostrados para JSON,
Writer/formato, HashMap con contexto, tipos genericos y captura directa de Child.
"""
from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"
PY = "3.12"
PROV = "std local de zig 0.16.0 (repo en lib/std)"
HDR = 'const std = @import("std");\n\n'
_SKIP = dict(type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
             skip_reason="sin driver diferencial todavia")


def entry(oid, name, intent, aliases, py, impl, tests, apis, *,
          errors=(), src="python", constraints=(), differences=(),
          side_effects=(), error_behavior="", ownership=""):
    return dict(
        operation_id=oid, name=name, intent=intent, aliases=aliases,
        source_lang=src, target_lang="zig", zig_version=ZIG, python_version=PY,
        platform="linux", py_ref=py, zig_impl=impl,
        zig_test=HDR + impl + "\n\n" + tests,
        apis_used=apis, constraints=list(constraints), preconditions=[],
        postconditions=[], differences=list(differences),
        error_signatures=list(errors), side_effects=list(side_effects),
        error_behavior=error_behavior, ownership_memory=ownership,
        provenance=PROV,
    )


ENTRIES = [
    entry(
        "zig0.16/stdlib016-ptrcast-result-type",
        "darle tipo de destino a @ptrCast cuando Zig no puede inferirlo",
        "Arreglar `@ptrCast must have a known result type`: declara el tipo del puntero de destino antes del cast. La conversión conserva const y solo cambia la vista del puntero.",
        ["@ptrCast must have a known result type", "tipo de resultado de ptrCast", "@ptrCast result type", "inferir destino ptrCast", "annotate @ptrCast destination type"],
        r'''// Zig 0.16: `const p = @ptrCast(raw)` no proporciona un tipo de destino.
fn asBytePointer(raw: *const anyopaque) *const u8 {
    const p = @ptrCast(raw);
    return p;
}''',
        r'''pub fn asBytePointer(raw: *const anyopaque) *const u8 {
    const p: *const u8 = @ptrCast(raw);
    return p;
}''',
        r'''test "el tipo destino hace explicito el ptrCast" {
    var byte: u8 = 42;
    const raw: *const anyopaque = @ptrCast(&byte);
    const result = asBytePointer(raw);
    try std.testing.expectEqual(@as(u8, 42), result.*);
}''',
        ["@ptrCast", "*const anyopaque", "*const u8"],
        errors=["@ptrCast must have a known result type"], src="zig-0.16",
        constraints=["el puntero de origen debe apuntar a un objeto valido del tipo destino"],
        differences=["anotar el resultado fija el tipo; no valida longitud, alineacion ni vida del objeto"],
        error_behavior="el error es de compilacion; el cast no comprueba el objeto en runtime",
        ownership="no asigna memoria; el puntero mantiene la vida del objeto de origen",
    ),
    entry(
        "zig0.16/stdlib016-json-parse-struct",
        "decodificar JSON directamente a un struct tipado",
        "Parsear un objeto JSON a un struct Zig con campos requeridos, opcionales y valores por defecto usando `std.json.parseFromSlice`. Configura explícitamente si se aceptan campos desconocidos y libera el arena con `Parsed.deinit()`.",
        ["parseFromSlice a struct Zig", "typed JSON struct parse Zig 0.16", "std.json.parseFromSlice Config", "parsear config JSON tipada", "JSON struct parser con defaults"],
        r'''import json
from dataclasses import dataclass

@dataclass
class Config:
    name: str
    retries: int = 3
    enabled: bool = True

cfg = Config(**json.loads('{"name":"worker","extra":1}'))''',
        r'''pub const Config = struct {
    name: []const u8,
    retries: u8 = 3,
    enabled: bool = true,
};

pub fn parseConfig(gpa: std.mem.Allocator, text: []const u8) !std.json.Parsed(Config) {
    return std.json.parseFromSlice(Config, gpa, text, .{
        .ignore_unknown_fields = true,
    });
}''',
        r'''test "parsea campos requeridos, opcionales y extra" {
    const text = "{\"name\":\"worker\",\"extra\":1}";
    const parsed = try parseConfig(std.testing.allocator, text);
    defer parsed.deinit();
    try std.testing.expectEqualStrings("worker", parsed.value.name);
    try std.testing.expectEqual(@as(u8, 3), parsed.value.retries);
    try std.testing.expect(parsed.value.enabled);
}

test "un campo requerido ausente es un error de parseo" {
    try std.testing.expectError(
        error.MissingField,
        parseConfig(std.testing.allocator, "{\"retries\":2}"),
    );
}''',
        ["std.json.parseFromSlice", "std.json.Parsed", "std.json.ParseOptions.ignore_unknown_fields"],
        constraints=["el campo name es requerido", "Parsed.deinit libera el arena de parseo"],
        differences=["los campos desconocidos se ignoran solo porque se activa ignore_unknown_fields", "los slices parseados deben vivir al menos tanto como Parsed"],
        error_behavior="SyntaxError, UnexpectedEndOfInput, MissingField y OutOfMemory se propagan",
        ownership="parseFromSlice devuelve Parsed; el llamador invoca deinit",
    ),
    entry(
        "zig0.16/stdlib016-json-stringify-struct",
        "serializar un struct Zig a JSON compacto en memoria",
        "Convertir un valor tipado a JSON con `std.json.Stringify.valueAlloc`; el slice resultante pertenece al llamador y se libera con el allocator usado.",
        ["std.json.Stringify.valueAlloc para struct", "JSON compacto de un struct", "serializar struct Zig a JSON", "json stringify typed value zig 0.16", "JSON encoder allocated bytes"],
        r'''import json
from dataclasses import asdict, dataclass

@dataclass
class Status:
    name: str
    count: int

json.dumps(asdict(Status("worker", 2)), separators=(",", ":"))''',
        r'''pub const Status = struct {
    name: []const u8,
    count: u32,
};

pub fn stringifyStatus(gpa: std.mem.Allocator, status: Status) ![]u8 {
    return std.json.Stringify.valueAlloc(gpa, status, .{});
}''',
        r'''test "serializa los campos del struct en orden de declaracion" {
    const output = try stringifyStatus(std.testing.allocator, .{
        .name = "worker",
        .count = 2,
    });
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("{\"name\":\"worker\",\"count\":2}", output);
}''',
        ["std.json.Stringify.valueAlloc", "std.json.Stringify.Options"],
        constraints=["la salida es compacta con opciones por defecto"],
        differences=["el resultado es un slice asignado que el llamador debe liberar", "el orden de los campos del struct determina el orden serializado"],
        error_behavior="OutOfMemory se propaga",
        ownership="valueAlloc devuelve bytes propiedad del llamador",
    ),
    entry(
        "zig0.16/stdlib016-writer-allocating",
        "construir texto con std.Io.Writer.Allocating",
        "Acumular texto de tamaño variable en un `std.Io.Writer.Allocating`, usar su `writer` para `print` y transferir la salida con `toOwnedSlice`.",
        ["std.Io.Writer.Allocating", "writer print a slice dinamico", "capturar salida de Io.Writer", "buffer que crece con Writer Zig 0.16", "Writer.Allocating.toOwnedSlice"],
        r'''parts = []
parts.append("items=")
parts.append(str(12))
text = "".join(parts)''',
        r'''pub fn makeLine(gpa: std.mem.Allocator, label: []const u8, count: usize) ![]u8 {
    var output: std.Io.Writer.Allocating = .init(gpa);
    defer output.deinit();
    try output.writer.print("{s}={d}", .{ label, count });
    return output.toOwnedSlice();
}''',
        r'''test "writer acumula texto formateado y transfiere el slice" {
    const output = try makeLine(std.testing.allocator, "items", 12);
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("items=12", output);
}''',
        ["std.Io.Writer.Allocating.init", "std.Io.Writer.print", "std.Io.Writer.Allocating.toOwnedSlice", "std.Io.Writer.Allocating.deinit"],
        constraints=["deinit libera solo lo que siga perteneciendo a Allocating", "toOwnedSlice transfiere la memoria al llamador"],
        differences=["el allocator se pasa al crear Allocating; el writer no almacena una copia del allocator"],
        error_behavior="WriteFailed y OutOfMemory se propagan",
        ownership="despues de toOwnedSlice, el llamador libera el resultado con gpa.free",
    ),
    entry(
        "zig0.16/stdlib016-format-f-any",
        "formatear tipos propios con {f} y valores arbitrarios con {any}",
        "Implementar `pub fn format(self, writer)` en un tipo propio para el especificador `{f}` y usar `{any}` cuando se quiere la representacion de depuracion de un valor sin un formato personalizado.",
        ["format propio {f} Zig 0.16", "std.Io.Writer {any}", "pub fn format tipo propio", "custom format method Zig writer", "format specifier f any"],
        r'''class Measurement:
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return f"{self.value} units"

f"{Measurement(12)} / {7!r}"''',
        r'''pub const Measurement = struct {
    value: i32,

    pub fn format(self: @This(), writer: *std.Io.Writer) std.Io.Writer.Error!void {
        try writer.print("{d} units", .{self.value});
    }
};

pub fn render(writer: *std.Io.Writer, measurement: Measurement, debug_value: anytype) !void {
    try writer.print("{f}/{any}", .{ measurement, debug_value });
}''',
        r'''test "f invoca format y any imprime un valor sin metodo propio" {
    var output: std.Io.Writer.Allocating = .init(std.testing.allocator);
    defer output.deinit();
    try render(&output.writer, .{ .value = 12 }, @as(u8, 7));
    try std.testing.expectEqualStrings("12 units/7", output.written());
}''',
        ["std.Io.Writer.print", "std.Io.Writer.Error", "format method", "{f}", "{any}"],
        constraints=["format recibe un writer de std.Io.Writer y devuelve std.Io.Writer.Error!void"],
        differences=["{f} delega en el metodo format del tipo", "{any} usa la representacion generica y puede ser mas verbosa que un formato de producto"],
        error_behavior="los errores de escritura se propagan",
        ownership="el writer y su buffer siguen bajo control del llamador",
    ),
    entry(
        "zig0.16/stdlib016-hashmap-custom-context",
        "usar std.HashMap con contexto de hash y comparacion propios",
        "Definir `hash` y `eql` en un Context propio para adaptar claves, y crear `std.HashMap` con `initContext`. El ejemplo indexa nombres ignorando mayusculas ASCII y conserva un seed configurable.",
        ["std.HashMap custom context", "HashMap initContext hash eql", "contexto propio de hash Zig", "case insensitive HashMap Zig", "HashMap hash function context"],
        r'''values = {"Port": 8080}
values["PORT"] = 8081
values["port"]''',
        r'''pub const NameContext = struct {
    seed: u64,

    pub fn hash(ctx: @This(), key: []const u8) u64 {
        var result = ctx.seed;
        for (key) |byte| result = result *% 131 + std.ascii.toLower(byte);
        return result;
    }

    pub fn eql(_: @This(), a: []const u8, b: []const u8) bool {
        return std.ascii.eqlIgnoreCase(a, b);
    }
};

pub const NameMap = std.HashMap([]const u8, u32, NameContext, 80);

pub fn initNameMap(gpa: std.mem.Allocator, seed: u64) NameMap {
    return NameMap.initContext(gpa, .{ .seed = seed });
}''',
        r'''test "el contexto propio controla hash y equivalencia" {
    var values = initNameMap(std.testing.allocator, 17);
    defer values.deinit();
    try values.put("Port", 8080);
    try std.testing.expectEqual(@as(?u32, 8080), values.get("PORT"));
    try values.put("PORT", 8081);
    try std.testing.expectEqual(@as(u32, 1), values.count());
    try std.testing.expectEqual(@as(?u32, 8081), values.get("port"));
}''',
        ["std.HashMap", "std.HashMap.initContext", "std.HashMap.put", "std.HashMap.get", "std.ascii.eqlIgnoreCase"],
        constraints=["las claves slice se prestan: deben seguir vivas mientras el mapa las almacena", "hash y eql deben tratar equivalentes las mismas claves"],
        differences=["a diferencia de StringHashMap, Context permite definir igualdad y hash para un tipo de clave o politica propia"],
        error_behavior="put puede fallar con OutOfMemory",
        ownership="el mapa es dueño de sus buffers internos; no duplica los slices clave",
    ),
    entry(
        "zig0.16/stdlib016-generic-list-comptime",
        "construir un tipo generico con fn List(comptime T: type) type",
        "Crear un tipo parametrizado en compilacion con una funcion que recibe `comptime T: type` y devuelve una estructura que almacena `std.ArrayList(T)`.",
        ["fn List(comptime T: type) type", "generic type constructor Zig", "lista generica comptime", "tipo generico con comptime Zig 0.16", "crear List de cualquier tipo"],
        r'''class List:
    def __init__(self):
        self.items = []

    def append(self, value):
        self.items.append(value)''',
        r'''pub fn List(comptime T: type) type {
    return struct {
        const Self = @This();
        allocator: std.mem.Allocator,
        items: std.ArrayList(T) = .empty,

        pub fn init(gpa: std.mem.Allocator) Self {
            return .{ .allocator = gpa };
        }

        pub fn append(self: *Self, value: T) std.mem.Allocator.Error!void {
            try self.items.append(self.allocator, value);
        }

        pub fn slice(self: *const Self) []const T {
            return self.items.items;
        }

        pub fn deinit(self: *Self) void {
            self.items.deinit(self.allocator);
        }
    };
}''',
        r'''test "List(T) instancia una ArrayList del tipo elegido en comptime" {
    var values = List(u32).init(std.testing.allocator);
    defer values.deinit();
    try values.append(4);
    try values.append(9);
    try std.testing.expectEqualSlices(u32, &.{ 4, 9 }, values.slice());
}''',
        ["comptime parameter", "type function", "std.ArrayList", "std.mem.Allocator"],
        constraints=["T se resuelve en compilacion al instanciar List(T)"],
        differences=["las instancias List(u8) y List(u32) son tipos Zig distintos", "la memoria de items usa el allocator guardado en cada instancia"],
        error_behavior="append puede fallar con OutOfMemory",
        ownership="cada instancia libera su ArrayList con el mismo allocator de init",
    ),
    entry(
        "zig0.16/stdlib016-child-capture-stdout",
        "capturar stdout al crear directamente un std.process.Child",
        "Iniciar un `std.process.Child` con `std.process.spawn`, conectar stdout a un pipe y leerlo hasta EOF con un limite antes de esperar al hijo.",
        ["std.process.spawn Child stdout pipe", "capturar stdout de Child Zig 0.16", "Child.stdout readerStreaming", "std.process.Child salida capturada", "leer pipe de proceso hijo Zig"],
        r'''import subprocess

result = subprocess.run(["/bin/echo", "captured"], capture_output=True, text=True)
assert result.stdout == "captured\n"''',
        r'''pub const Capture = struct {
    allocator: std.mem.Allocator,
    stdout: []u8,
    term: std.process.Child.Term,

    pub fn deinit(self: *@This()) void {
        self.allocator.free(self.stdout);
    }
};

pub fn captureEcho(io: std.Io, gpa: std.mem.Allocator) !Capture {
    var child = try std.process.spawn(io, .{
        .argv = &.{ "/bin/echo", "captured" },
        .stdin = .ignore,
        .stdout = .pipe,
        .stderr = .ignore,
    });
    defer child.kill(io);

    var read_buffer: [128]u8 = undefined;
    var reader = child.stdout.?.readerStreaming(io, &read_buffer);
    const stdout = try reader.interface.allocRemaining(gpa, .limited(1024));
    errdefer gpa.free(stdout);
    const term = try child.wait(io);
    return .{ .allocator = gpa, .stdout = stdout, .term = term };
}''',
        r'''test "stdout del hijo se lee del pipe y se espera su terminacion" {
    var result = try captureEcho(std.testing.io, std.testing.allocator);
    defer result.deinit();
    try std.testing.expectEqualStrings("captured\n", result.stdout);
    try std.testing.expect(result.term == .exited);
    try std.testing.expectEqual(@as(u8, 0), result.term.exited);
}''',
        ["std.process.spawn", "std.process.Child", "std.process.Child.wait", "std.Io.File.readerStreaming", "std.Io.Reader.allocRemaining", "std.Io.Limit.limited"],
        constraints=["stdout se limita a 1024 bytes", "stderr se descarta para que el ejemplo solo tenga que drenar un pipe", "la ruta /bin/echo corresponde a Linux"],
        differences=["std.process.run es mas conveniente para capturar stdout y stderr simultaneamente; el ejemplo directo muestra Child y su pipe de stdout", "sin shell, argv pasa cada argumento por separado"],
        side_effects=["lanza un proceso hijo /bin/echo"],
        error_behavior="SpawnError, errores de lectura y WaitError se propagan; la salida excesiva da StreamTooLong",
        ownership="Capture.deinit libera stdout; el hijo se espera antes de devolver el resultado",
    ),
]


CONTRACTS = {
    e["operation_id"]: _c(None, None, None, [], **_SKIP)
    for e in ENTRIES
}
