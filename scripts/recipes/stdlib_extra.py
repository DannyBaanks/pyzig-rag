"""Recetas stdlib_extra: huecos de la std 0.16 y firmas minadas sin receta.

- Migracion (source_lang `zig-0.13/0.14` o `zig-0.16`): `error_signatures` son lineas
  `error:` REALES copiadas de compilar el codigo roto con zig 0.16.0 (sin ruta ni posicion).
- Python -> Zig: csv.reader simple, datetime (epoch -> UTC), argparse con subcomandos, y
  una entrada `gap` NOT_DEMONSTRATED para `re` (la std 0.16 no trae motor de regex).
Cada zig_test se verifica con `zig test` (Zig 0.16.0) en scripts/run_gates.py."""
from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"; PY = "3.12"; PROV = "std local de zig 0.16.0 (repo en lib/std); errores copiados de `zig test` 0.16.0"
SRC_OLD = "zig-0.13/0.14"
HDR = 'const std = @import("std");\n\n'
_SKIP = dict(type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
             skip_reason="sin driver diferencial todavia")


def entry(oid, name, intent, aliases, old, impl, tests, apis, constraints, differences,
          sigs, src=SRC_OLD, side_effects=None, error_behavior="", ownership=""):
    return dict(
        operation_id=oid, name=name, intent=intent, aliases=aliases,
        source_lang=src, target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=old, zig_impl=impl, zig_test=HDR + impl + "\n\n" + tests,
        apis_used=apis, constraints=constraints, differences=differences,
        error_signatures=sigs, side_effects=side_effects or [],
        error_behavior=error_behavior, ownership_memory=ownership, provenance=PROV)


def py_entry(oid, name, intent, aliases, py, impl, tests, apis, constraints, differences,
             side_effects=None, error_behavior="", ownership=""):
    return dict(
        operation_id=oid, name=name, intent=intent, aliases=aliases,
        source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=py, zig_impl=impl, zig_test=HDR + impl + "\n\n" + tests,
        apis_used=apis, constraints=constraints, differences=differences,
        error_signatures=[], side_effects=side_effects or [],
        error_behavior=error_behavior, ownership_memory=ownership, provenance=PROV)


ENTRIES = []

# ---------------------------------------------------------------- openDirAbsolute
ENTRIES.append(entry(
    "zig0.16/migrate-open-dir-absolute",
    "abrir un directorio por ruta absoluta: std.fs.openDirAbsolute pasa a std.Io.Dir",
    "Abrir un directorio por ruta absoluta en Zig 0.16: std.fs.openDirAbsolute ya no existe en el modulo std.fs; la llamada es std.Io.Dir.openDirAbsolute(io, ruta, opciones), que recibe io y exige ruta absoluta.",
    ["std.fs.openDirAbsolute", "openDirAbsolute", "abrir directorio absoluto", "fs.openDirAbsolute removed", "Io.Dir.openDirAbsolute", "migrar 0.14 a 0.16", "has no member named openDirAbsolute", "abrir carpeta con ruta absoluta", "iterar directorio absoluto"],
    '''// Zig 0.13/0.14 (NO compila en 0.16)
const std = @import("std");
pub fn abrirDirectorio(ruta: []const u8) !void {
    var d = try std.fs.openDirAbsolute(ruta, .{ .iterate = true });
    defer d.close();
}
test "uso" {
    try abrirDirectorio("/tmp");
}''',
    '''pub fn abrirDirectorio(io: std.Io, ruta: []const u8) !std.Io.Dir {
    // 0.16: la apertura es de std.Io.Dir; `io` es el mismo que usa el resto de operaciones
    return std.Io.Dir.openDirAbsolute(io, ruta, .{ .iterate = true });
}''',
    '''test "abre un directorio absoluto y lista sus entradas" {
    const io = std.testing.io;
    const gpa = std.testing.allocator;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "a.txt", .data = "x" });
    const ruta = try tmp.dir.realPathFileAlloc(io, ".", gpa);
    defer gpa.free(ruta);
    var dir = try abrirDirectorio(io, ruta);
    defer dir.close(io);
    var it = dir.iterate();
    const e = (try it.next(io)).?;
    try std.testing.expectEqualStrings("a.txt", e.name);
    try std.testing.expect((try it.next(io)) == null);
}''',
    ["std.Io.Dir.openDirAbsolute", "std.Io.Dir.iterate", "std.Io.Dir.close", "std.Io.Dir.realPathFileAlloc", "std.testing.tmpDir", "std.fs.path.isAbsolute"],
    ["la ruta DEBE ser absoluta: openDirAbsolute hace assert(isAbsolute), no devuelve error",
     "iterar exige abrir con .iterate = true",
     "dir.close(io) recibe io (0.16)"],
    ["0.14: std.fs.openDirAbsolute(ruta, opciones) devolvia std.fs.Dir; 0.16: std.Io.Dir.openDirAbsolute(io, ruta, opciones) devuelve std.Io.Dir",
     "la forma 0.13/0.14 NO se compilo en este worktree (solo zig 0.16.0 disponible); se documenta la firma 0.16 verificada en lib/std/Io/Dir.zig",
     "el mismo cambio aplica a openDir/openFile: pasan por Io.Dir con io"],
    ["error: root source file struct 'fs' has no member named 'openDirAbsolute'"],
    side_effects=["abre un descriptor de directorio (cerrar con close(io))"],
    error_behavior="errores de apertura (FileNotFound, AccessDenied, NotDir) como OpenError",
    ownership="el llamador cierra el Dir con dir.close(io)"))

# ---------------------------------------------------------------- ArrayList.writer()
ENTRIES.append(entry(
    "zig0.16/migrate-arraylist-writer",
    "metodos del ArrayList unmanaged que ya no existen: writer(), campo allocator y su reemplazo",
    "Metodos del ArrayList unmanaged que ya no existen en Zig 0.16: no hay writer() ni campo allocator; para formatear dentro de la lista se usa list.print(gpa, fmt, args), y cada metodo que reserva memoria recibe el allocator explicito.",
    ["ArrayList writer", "list.writer()", "writer del ArrayList", "ArrayList(u8).writer", "print en ArrayList", "formatear en ArrayList", "no field or member function named writer", "list.allocator", "campo allocator del ArrayList", "no field named allocator", "migrar 0.14 a 0.16", "std.fmt en lista de bytes", "unmanaged print", "metodo que no existe en ArrayList"],
    '''// codigo a medio migrar: ya usa .empty y gpa, pero aun llama a writer() (NO compila en 0.16)
const std = @import("std");
pub fn formatea(gpa: std.mem.Allocator, n: i32, nombre: []const u8) ![]u8 {
    var list: std.ArrayList(u8) = .empty;
    errdefer list.deinit(gpa);
    const w = list.writer();
    try w.print("{s}={d}", .{ nombre, n });
    return list.toOwnedSlice(gpa);
}
test "uso" {
    const s = try formatea(std.testing.allocator, 1, "x");
    std.testing.allocator.free(s);
}''',
    '''pub fn formatea(gpa: std.mem.Allocator, n: i32, nombre: []const u8) ![]u8 {
    var buf: std.ArrayList(u8) = .empty;
    errdefer buf.deinit(gpa);
    // 0.16: print recibe el allocator; no hay writer() que lo guarde
    try buf.print(gpa, "{s}={d}", .{ nombre, n });
    return buf.toOwnedSlice(gpa);
}''',
    '''test "print acumula el texto formateado" {
    const gpa = std.testing.allocator;
    const s = try formatea(gpa, 42, "x");
    defer gpa.free(s);
    try std.testing.expectEqualStrings("x=42", s);
}

test "un fallo de memoria se propaga y no deja fugas" {
    var fallo = std.testing.FailingAllocator.init(std.testing.allocator, .{ .fail_index = 0 });
    try std.testing.expectError(error.OutOfMemory, formatea(fallo.allocator(), 1, "y"));
}''',
    ["std.ArrayList.print", "std.ArrayList.toOwnedSlice", "std.ArrayList.deinit", "std.testing.FailingAllocator"],
    ["sin writer(): para escribir en streams usa std.Io.Writer.Allocating si hace falta un *std.Io.Writer",
     "list.allocator (campo) tampoco existe: el error es 'no field named 'allocator' in struct 'array_list.Aligned(u8,null)'' (verificado con zig 0.16.0); pasa gpa a cada metodo",
     "init(gpa) y el resto de la forma managed: ver zig0.16/migrate-arraylist-unmanaged"],
    ["0.14: ArrayList(u8).init(gpa) + list.writer().print(...); 0.16: ArrayList unmanaged + list.print(gpa, ...)",
     "toOwnedSlice y deinit tambien reciben el allocator"],
    ["error: no field or member function named 'writer' in 'array_list.Aligned(u8,null)'"],
    error_behavior="OutOfMemory si no cabe el texto",
    src="zig-0.16",
    ownership="toOwnedSlice entrega el slice al llamador (gpa.free)"))

# ---------------------------------------------------------------- [:0] slice -> ?[*:0]
ENTRIES.append(entry(
    "zig0.16/cstring-sentinel-slice-ptr",
    "pasar un slice terminado en cero ([:0]const u8) donde se espera ?[*:0]const u8",
    "Pasar un slice con sentinela 0 a una funcion que espera un puntero C ?[*:0]const u8: se pasa el campo .ptr del slice, no la direccion del slice (&slice da un puntero a slice, otro tipo).",
    ["expected type ?[*:0]const u8", "[*:0]const u8 found *const [:0]const u8", "slice a puntero C", "puntero a slice centinela", "many-pointer", "[:0]const u8 a char*", "usar .ptr", "&slice en vez de slice.ptr", "cstring argumento"],
    '''// codigo que NO compila en 0.16: &nombre es *const [:0]const u8, no un many-pointer
const std = @import("std");
fn longitudC(s: ?[*:0]const u8) usize {
    const p = s orelse return 0;
    return std.mem.len(p);
}
test "longitud" {
    const nombre: [:0]const u8 = "hola";
    _ = longitudC(&nombre);
}''',
    '''fn longitudC(s: ?[*:0]const u8) usize {
    const p = s orelse return 0;
    return std.mem.len(p);
}''',
    '''test "el campo .ptr del slice sentinela es el puntero C" {
    const nombre: [:0]const u8 = "hola";
    try std.testing.expectEqual(@as(usize, 4), longitudC(nombre.ptr));
}

test "null es cadena vacia" {
    try std.testing.expectEqual(@as(usize, 0), longitudC(null));
}''',
    ["std.mem.len", "std.mem.span", "std.mem.sliceTo"],
    ["`.ptr` de un [:0]T es [*:0]T; `&slice` es *const [:0]T y no coerciona a puntero C",
     "en FFI (extern fn) el mismo cambio aplica; el gate con -lc queda fuera de este recipe"],
    ["la version 0.13/0.14 se consideraba igual de valida: no se compilo aqui (solo zig 0.16.0)",
     "para convertir a slice en la direccion contraria ver zig0.16/cstring-span-slice-to"],
    ["error: expected type '?[*:0]const u8', found '*const [:0]const u8'"],
    src="zig-0.16",
    error_behavior="ninguno en runtime: el error es de tipos en compilacion",
    ownership="no asigna memoria; el puntero vive lo que el slice original"))

# ---------------------------------------------------------------- csv.reader
ENTRIES.append(py_entry(
    "zig0.16/csv-reader-line-quoted",
    "leer una linea CSV con campos entre comillas (csv.reader)",
    "Partir una linea CSV en campos respetando comas dentro de comillas y el escape de comilla doble (\"\"), como csv.reader de Python con el dialecto por defecto.",
    ["csv.reader", "csv reader", "leer csv", "split csv con comillas", "campos entre comillas", "csv.reader linea", "parsear csv simple", "comillas dobles csv", "separar por coma con comillas"],
    r'''import csv, io
list(csv.reader(io.StringIO('a,"b,c",d')))              # [['a', 'b,c', 'd']]
list(csv.reader(io.StringIO('"di ""hola""",x')))         # [['di "hola"', 'x']]
list(csv.reader(io.StringIO('a,,b')))                    # [['a', '', 'b']]''',
    r'''/// Parte una linea (sin salto final) en campos. Los campos son copias propias: libera con freeCampos.
pub fn parseCsvLine(gpa: std.mem.Allocator, line: []const u8) ![][]u8 {
    var campos: std.ArrayList([]u8) = .empty;
    errdefer {
        for (campos.items) |c| gpa.free(c);
        campos.deinit(gpa);
    }
    var campo: std.ArrayList(u8) = .empty;
    defer campo.deinit(gpa);
    var en_comillas = false;
    var i: usize = 0;
    while (i < line.len) : (i += 1) {
        const c = line[i];
        if (en_comillas) {
            if (c == '"') {
                if (i + 1 < line.len and line[i + 1] == '"') {
                    try campo.append(gpa, '"');
                    i += 1;
                } else {
                    en_comillas = false;
                }
            } else {
                try campo.append(gpa, c);
            }
        } else if (c == ',') {
            const f = try campo.toOwnedSlice(gpa);
            campos.append(gpa, f) catch |e| {
                gpa.free(f);
                return e;
            };
        } else if (c == '"' and campo.items.len == 0) {
            en_comillas = true;
        } else {
            try campo.append(gpa, c);
        }
    }
    const f = try campo.toOwnedSlice(gpa);
    campos.append(gpa, f) catch |e| {
        gpa.free(f);
        return e;
    };
    return campos.toOwnedSlice(gpa);
}

pub fn freeCampos(gpa: std.mem.Allocator, campos: [][]u8) void {
    for (campos) |c| gpa.free(c);
    gpa.free(campos);
}''',
    r'''test "coma dentro de comillas no separa" {
    const gpa = std.testing.allocator;
    const c = try parseCsvLine(gpa, "a,\"b,c\",d");
    defer freeCampos(gpa, c);
    try std.testing.expectEqual(@as(usize, 3), c.len);
    try std.testing.expectEqualStrings("a", c[0]);
    try std.testing.expectEqualStrings("b,c", c[1]);
    try std.testing.expectEqualStrings("d", c[2]);
}

test "comilla doble escapada y campos vacios" {
    const gpa = std.testing.allocator;
    const c = try parseCsvLine(gpa, "\"di \"\"hola\"\"\",x");
    defer freeCampos(gpa, c);
    try std.testing.expectEqualStrings("di \"hola\"", c[0]);
    try std.testing.expectEqualStrings("x", c[1]);
    const v = try parseCsvLine(gpa, "a,,b");
    defer freeCampos(gpa, v);
    try std.testing.expectEqual(@as(usize, 3), v.len);
    try std.testing.expectEqual(@as(usize, 0), v[1].len);
}

test "comilla en medio de un campo sin comillas es literal" {
    const gpa = std.testing.allocator;
    const c = try parseCsvLine(gpa, "a\"b,c");
    defer freeCampos(gpa, c);
    try std.testing.expectEqualStrings("a\"b", c[0]);
    try std.testing.expectEqualStrings("c", c[1]);
}''',
    ["std.ArrayList.append", "std.ArrayList.toOwnedSlice", "std.ArrayList.deinit", "std.mem.Allocator.free"],
    ["sin soporte de saltos de linea dentro de un campo entrecomillado (una linea por llamada)",
     "el llamador quita el salto final (\\n o \\r\\n) antes de llamar"],
    ["csv.reader no devuelve nada para una linea vacia; parseCsvLine devuelve un campo vacio",
     "dialecto simple: sin delimitador configurable, sin quoting de otros tipos, sin csv.DictReader"],
    side_effects=[],
    error_behavior="OutOfMemory",
    ownership="cada campo y el slice exterior son del llamador: libera con freeCampos"))

# ---------------------------------------------------------------- datetime epoch -> UTC
ENTRIES.append(py_entry(
    "zig0.16/epoch-to-utc-ymd-hms",
    "convertir segundos desde epoch a Y-M-D H:M:S en UTC (datetime)",
    "Formatear un instante Unix (segundos desde 1970-01-01T00:00:00Z) como 'AAAA-MM-DD HH:MM:SS' en UTC, sin zona horaria local, con std.time.epoch.",
    ["datetime.fromtimestamp", "datetime.utcfromtimestamp", "strftime %Y-%m-%d", "epoch a fecha", "unix timestamp a fecha", "fecha desde segundos", "std.time.epoch", "EpochSeconds", "fecha UTC", "anio mes dia desde epoch"],
    r'''import datetime as d
d.datetime.fromtimestamp(0, tz=d.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")      # '1970-01-01 00:00:00'
d.datetime.fromtimestamp(951782400, tz=d.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")  # '2000-02-29 00:00:00'
d.datetime.fromtimestamp(1700000000, tz=d.timezone.utc).strftime("%Y-%m-%d %H:%M:%S") # '2023-11-14 22:13:20'
''',
    r'''/// Segundos desde epoch (UTC) a "AAAA-MM-DD HH:MM:SS". Libera el resultado con gpa.free.
pub fn isoUtc(gpa: std.mem.Allocator, segundos: u64) ![]u8 {
    const es: std.time.epoch.EpochSeconds = .{ .secs = segundos };
    const anio_dia = es.getEpochDay().calculateYearDay();
    const mes_dia = anio_dia.calculateMonthDay();
    const hora = es.getDaySeconds();
    return std.fmt.allocPrint(gpa, "{d:0>4}-{d:0>2}-{d:0>2} {d:0>2}:{d:0>2}:{d:0>2}", .{
        anio_dia.year,
        mes_dia.month.numeric(),
        @as(u8, mes_dia.day_index) + 1,
        hora.getHoursIntoDay(),
        hora.getMinutesIntoHour(),
        hora.getSecondsIntoMinute(),
    });
}''',
    r'''test "epoch cero es 1970-01-01" {
    const gpa = std.testing.allocator;
    const s = try isoUtc(gpa, 0);
    defer gpa.free(s);
    try std.testing.expectEqualStrings("1970-01-01 00:00:00", s);
}

test "anio bisiesto 2000 y ultimo segundo del dia" {
    const gpa = std.testing.allocator;
    const a = try isoUtc(gpa, 951782400);
    defer gpa.free(a);
    try std.testing.expectEqualStrings("2000-02-29 00:00:00", a);
    const b = try isoUtc(gpa, 86399);
    defer gpa.free(b);
    try std.testing.expectEqualStrings("1970-01-01 23:59:59", b);
}

test "1700000000 y 2100 (no bisiesto)" {
    const gpa = std.testing.allocator;
    const a = try isoUtc(gpa, 1700000000);
    defer gpa.free(a);
    try std.testing.expectEqualStrings("2023-11-14 22:13:20", a);
    const b = try isoUtc(gpa, 4102444800);
    defer gpa.free(b);
    try std.testing.expectEqualStrings("2100-01-01 00:00:00", b);
}''',
    ["std.time.epoch.EpochSeconds", "std.time.epoch.EpochDay.calculateYearDay", "std.time.epoch.YearAndDay.calculateMonthDay", "std.time.epoch.Month.numeric", "std.fmt.allocPrint"],
    ["solo UTC: no hay zona horaria ni horario de verano",
     "segundos sin signo (u64): datetime admite epoch negativo y esta receta no"],
    ["datetime.fromtimestamp(ts, tz=UTC) con strftime; en 0.16: EpochSeconds.getEpochDay().calculateYearDay() y calculateMonthDay() (0-based: sumar 1 al dia)",
     "std.time.epoch no conoce anios fuera de u16 ni la fecha gregoriana proleptica anterior a 1970 sin signo"],
    side_effects=[],
    error_behavior="OutOfMemory de allocPrint",
    ownership="el llamador libera la cadena con gpa.free"))

# ---------------------------------------------------------------- argparse subcomandos
ENTRIES.append(py_entry(
    "zig0.16/argparse-subcommands",
    "analizar argumentos con subcomandos (argparse add_subparsers) sin dependencias",
    "Interpretar argv con un subcomando obligatorio ('add N', 'list [-v]') y errores explicitos, como argparse con add_subparsers, sobre un slice de argumentos ya reunido.",
    ["argparse subcommands", "add_subparsers", "subcomandos cli", "argparse subparser", "subcommand parser", "git style subcommands", "parsear subcomandos", "cli add list", "argumentos de subcomando", "argparse minimo"],
    r'''import argparse
p = argparse.ArgumentParser(prog="tool")
sub = p.add_subparsers(dest="cmd", required=True)
a = sub.add_parser("add"); a.add_argument("n", type=int)
l = sub.add_parser("list"); l.add_argument("-v", action="store_true")
p.parse_args(["add", "5"])          # Namespace(cmd='add', n=5)
p.parse_args(["list", "-v"])        # Namespace(cmd='list', v=True)''',
    r'''/// Orden ya interpretada. argv[0] es el nombre del programa.
pub const Orden = union(enum) {
    add: i64,
    list: struct { verbose: bool },
};

pub const ErrorArgs = error{ MissingCommand, UnknownCommand, MissingArgument, InvalidInt, UnknownOption };

pub fn parsear(argv: []const []const u8) ErrorArgs!Orden {
    if (argv.len < 2) return error.MissingCommand;
    const sub = argv[1];
    const resto = argv[2..];
    if (std.mem.eql(u8, sub, "add")) {
        if (resto.len < 1) return error.MissingArgument;
        const n = std.fmt.parseInt(i64, resto[0], 10) catch return error.InvalidInt;
        return .{ .add = n };
    }
    if (std.mem.eql(u8, sub, "list")) {
        var verbose = false;
        for (resto) |a| {
            if (std.mem.eql(u8, a, "-v")) {
                verbose = true;
            } else {
                return error.UnknownOption;
            }
        }
        return .{ .list = .{ .verbose = verbose } };
    }
    return error.UnknownCommand;
}''',
    r'''test "add toma un entero" {
    const o = try parsear(&.{ "tool", "add", "5" });
    try std.testing.expectEqual(@as(i64, 5), o.add);
}

test "list con y sin -v" {
    const v = try parsear(&.{ "tool", "list", "-v" });
    try std.testing.expect(v.list.verbose);
    const n = try parsear(&.{ "tool", "list" });
    try std.testing.expect(!n.list.verbose);
}

test "errores: sin subcomando, subcomando desconocido, falta argumento, entero invalido, opcion desconocida" {
    try std.testing.expectError(error.MissingCommand, parsear(&.{"tool"}));
    try std.testing.expectError(error.UnknownCommand, parsear(&.{ "tool", "nope" }));
    try std.testing.expectError(error.MissingArgument, parsear(&.{ "tool", "add" }));
    try std.testing.expectError(error.InvalidInt, parsear(&.{ "tool", "add", "x" }));
    try std.testing.expectError(error.UnknownOption, parsear(&.{ "tool", "list", "--todo" }));
}''',
    ["std.fmt.parseInt", "std.mem.eql"],
    ["solo subcomandos add y list con -v; sin --help automatico ni mensajes de uso",
     "los argumentos se reunen fuera (ver zig0.16/process-args-iterate) y se pasan como slice: la funcion es pura y testeable",
     "argparse de Python sale con codigo 2 y escribe el uso; aqui solo se devuelve el error"],
    ["argparse: add_subparsers(dest=..., required=True) hace obligatorio el subcomando; aqui MissingCommand",
     "argparse con type=int lanza error de uso; aqui InvalidInt"],
    side_effects=[],
    error_behavior="errores de la union ErrorArgs; nunca termina el proceso",
    ownership="no asigna memoria: argv y sus cadenas son del llamador"))

# ---------------------------------------------------------------- gap: re
ENTRIES.append(dict(
    operation_id="zig0.16/re-regex-gap",
    name="expresiones regulares (re) NO DEMOSTRADO: la std 0.16 no trae motor de regex",
    intent="Buscar, extraer o sustituir con expresiones regulares como re.search, re.findall, re.sub o re.compile en Zig 0.16 sin dependencias externas.",
    aliases=["re.search", "re.findall", "re.sub", "re.compile", "regex en zig", "expresion regular", "regular expression", "regex std", "patron con grupos", "pattern matching regex", "buscar con regex", "reemplazar con regex", "re.match"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''import re
re.search(r"\d+", "abc 123 def").group()        # '123'
re.findall(r"[a-z]+@\w+\.com", "x a@b.com y")    # ['a@b.com']
re.sub(r"\s+", " ", "a   b\tc")                  # 'a b c'
''',
    zig_impl=r'''// NO HAY EQUIVALENTE en la std 0.16: no existe modulo de expresiones regulares.
// Comprobado: `ziggrep -ri regex lib/std` solo devuelve textos de ejemplo en comentarios de
// Io/Threaded.zig y process/Args.zig. Alternativas reales:
//  - patrones fijos: std.mem.indexOf / std.mem.containsAtLeast / splitSequence
//  - tokens por conjunto de separadores: std.mem.tokenizeAny / splitAny
//  - patrones concretos: escribir el matcher a mano (ver zig0.16/string-split-strip-format)
//  - motor completo: dependencia externa (no en std) o FFI a libc regcomp/regexec (con -lc)''',
    zig_test=None,
    apis_used=["std.mem.indexOf", "std.mem.tokenizeAny", "std.mem.splitSequence"],
    constraints=["sin motor de regex en la std 0.16; las alternativas cubren solo patrones fijos o sencillos"],
    preconditions=["el patron es fijo o de forma conocida"],
    postconditions=["N/D"],
    side_effects=[],
    error_behavior="N/D",
    ownership_memory="N/D",
    differences=[
        "re.findall/re.sub con grupos y cuantificadores no tiene receta: NO DEMOSTRADO",
        "re.compile no existe; cada patron es codigo propio o FFI",
        "las alternativas (indexOf, tokenizeAny) NO son regex: \\d+, [a-z]+ o alternancia no se expresan",
    ],
    provenance="NO_GATE: la std 0.16 no trae motor de regex (comprobado con ziggrep en lib/std); sin zig_test, no hay API que demostrar",
    status="NOT_DEMONSTRATED",
    entry_type="gap",
))

CONTRACTS = {e["operation_id"]: _c(None, None, None, [], **_SKIP) for e in ENTRIES}
