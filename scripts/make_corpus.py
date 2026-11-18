#!/usr/bin/env python3
"""Genera corpus/pyzig.corpus.jsonl: recetas Python->Zig 0.16.0 verificadas contra
la std local (zig 0.16.0, /usr/lib/std o ~/.local/.../lib/std).

Este script es la ESPECIFICACION del corpus; la escritura la hace el unico
escritor (`pyzig.corpus.write_all`), que recalcula `content_sha256` de cada
entrada y conserva la evidencia previa solo si el codigo probado no cambio.
"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pyzig import corpus as corpus_mod          # noqa: E402
from pyzig.fuzz import contracts                 # noqa: E402

ZIG = "0.16.0"
PY = "3.12"
PROV = "std local de zig 0.16.0 (repo en lib/std)"

E = []

E.append(dict(
    operation_id="zig0.16/subprocess-run-capture",
    name="ejecutar proceso externo y capturar streams",
    intent="Ejecutar un comando externo, capturar stdout y stderr por separado, distinguir salida exitosa de fallo y limitar el tamano de la captura.",
    aliases=["subprocess.run","capture_output","check_output","Popen","run process","child process","exit code","timeout","lanzar comando","codigo de salida","saber si fallo","exito o fallo","check_call"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''import subprocess
r = subprocess.run(["printf","hola"], capture_output=True, text=True)
r.returncode, r.stdout, r.stderr''',
    zig_impl='''fn runCapture(gpa: std.mem.Allocator, io: std.Io, argv: []const []const u8) !std.process.RunResult {
    return std.process.run(gpa, io, .{
        .argv = argv,
        .stdout_limit = .limited(64 * 1024),
        .stderr_limit = .limited(64 * 1024),
    });
}
// term: .exited => |code|, .signal, .stopped, .unknown''',
    zig_test='''const std = @import("std");

fn runCapture(gpa: std.mem.Allocator, io: std.Io, argv: []const []const u8) !std.process.RunResult {
    return std.process.run(gpa, io, .{
        .argv = argv,
        .stdout_limit = .limited(64 * 1024),
        .stderr_limit = .limited(64 * 1024),
    });
}

test "captura stdout y exit 0" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    const res = try runCapture(alloc, io, &.{ "printf", "hola" });
    defer { alloc.free(res.stdout); alloc.free(res.stderr); }
    try std.testing.expect(res.term == .exited);
    try std.testing.expectEqual(@as(u8, 0), res.term.exited);
    try std.testing.expectEqualStrings("hola", res.stdout);
}

test "exit distinto de 0 y stderr visible" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    const res = try runCapture(alloc, io, &.{ "sh", "-c", "echo boom >&2; exit 3" });
    defer { alloc.free(res.stdout); alloc.free(res.stderr); }
    try std.testing.expectEqual(@as(u8, 3), res.term.exited);
    try std.testing.expect(std.mem.indexOf(u8, res.stderr, "boom") != null);
}

test "limite de captura provoca StreamTooLong" {
    const alloc = std.testing.allocator;
    try std.testing.expectError(error.StreamTooLong, std.process.run(alloc, std.testing.io, .{
        .argv = &.{ "printf", "hola" },
        .stdout_limit = .limited(2),
    }));
}

test "timeout aborta la espera" {
    const alloc = std.testing.allocator;
    try std.testing.expectError(error.Timeout, std.process.run(alloc, std.testing.io, .{
        .argv = &.{ "sleep", "5" },
        .timeout = .{ .duration = .{ .raw = std.Io.Duration.fromMilliseconds(300), .clock = .real } },
    }));
}''',
    apis_used=["std.process.run","std.process.RunOptions","std.process.Child.Term","std.process.RunResult","Io.Limit.limited","Io.Timeout.duration","Io.Duration.fromMilliseconds"],
    constraints=["sin root","gpa propio por llamada","io inyectado"],
    preconditions=["argv[0] resoluble en PATH del padre"],
    postconditions=["memoria de stdout/stderr owned by caller (gpa.free)"],
    side_effects=["ejecuta un programa real"],
    error_behavior="error.StreamTooLong al pasarse limite; error.Timeout al expirar; errores de spawn en RunError; term.signal/senala muerte por senal.",
    ownership_memory="stdout y stderr se devuelven en buffers del gpa; liberar con free.",
    differences=["subprocess.run con text=True decodifica; Zig devuelve bytes crudos","Python expone returncode -N si senal; Zig usa term.signal","timeout de Python mata al hijo; aqui el run devuelve error.Timeout"],
    provenance=PROV,
))

E.append(dict(
    operation_id="zig0.16/read-file-text-limited",
    name="leer archivo de texto con limite",
    intent="Leer el contenido completo de un archivo a memoria con un tope de tamano, distinguiendo archivo ausente de otros errores de E/S.",
    aliases=["read_text","open().read()","pathlib read","leer archivo","FileNotFound","StreamTooLong","read file"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''from pathlib import Path
try:
    data = Path("/etc/wifihost/config").read_text()
except FileNotFoundError:
    data = ""''',
    zig_impl='''fn readText(gpa: std.mem.Allocator, io: std.Io, dir: *std.Io.Dir, sub_path: []const u8, limit: usize) ![]u8 {
    return dir.readFileAlloc(io, sub_path, gpa, .limited(limit));
}
// ausente => error.FileNotFound; pasado de limite => error.StreamTooLong''',
    zig_test='''const std = @import("std");

fn readText(gpa: std.mem.Allocator, io: std.Io, dir: *std.Io.Dir, sub_path: []const u8, limit: usize) ![]u8 {
    return dir.readFileAlloc(io, sub_path, gpa, .limited(limit));
}

test "lee contenido escrito" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "cfg", .data = "hola\\n" });
    const got = try readText(alloc, io, &tmp.dir, "cfg", 1024);
    defer alloc.free(got);
    try std.testing.expectEqualStrings("hola\\n", got);
}

test "ausente da FileNotFound" {
    const alloc = std.testing.allocator;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try std.testing.expectError(error.FileNotFound, readText(alloc, std.testing.io, &tmp.dir, "no-existe", 1024));
}

test "limite provoca StreamTooLong" {
    const alloc = std.testing.allocator;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(std.testing.io, .{ .sub_path = "cfg", .data = "hola\\n" });
    try std.testing.expectError(error.StreamTooLong, readText(alloc, std.testing.io, &tmp.dir, "cfg", 2));
}''',
    apis_used=["std.Io.Dir.readFileAlloc","Io.Limit.limited","std.testing.tmpDir","Io.Dir.writeFile"],
    constraints=["sin root","gpa propio"],
    preconditions=["dir abierto por openDirAbsolute o tmpDir"],
    postconditions=["slice owned by caller"],
    side_effects=[],
    error_behavior="error.FileNotFound ausente; error.StreamTooLong pasado el limite; AccessDenied sin permiso.",
    ownership_memory="readFileAlloc asigna con gpa; caller libera.",
    differences=["Python read_text decodifica UTF-8; Zig devuelve bytes","Python lanza IsADirectoryError si es dir; aqui error.IsDir"],
    provenance=PROV,
))

E.append(dict(
    operation_id="zig0.16/write-file-bytes-atomic",
    name="escribir archivo (truncar o atomico)",
    intent="Escribir bytes a un archivo truncando su contenido previo, o hacerlo de forma atomica via temporal + rename para no dejar corrupcion a mitad.",
    aliases=["write_bytes","write_text","Path.write_text","escritura atomica","atomic write","tmp + rename","truncate"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''from pathlib import Path
p = Path("/run/wifihost/state")
p.write_text("SCENARIO=B\\n")            # truncar
tmp = p.with_suffix(".tmp"); tmp.write_text(x); tmp.replace(p)  # atomico''',
    zig_impl='''fn writeBytes(io: std.Io, dir: *std.Io.Dir, sub_path: []const u8, data: []const u8) !void {
    try dir.writeFile(io, .{ .sub_path = sub_path, .data = data, .flags = .{ .truncate = true } });
}

fn writeBytesAtomic(io: std.Io, dir: *std.Io.Dir, sub_path: []const u8, data: []const u8) !void {
    var af = try dir.createFileAtomic(io, sub_path, .{ .replace = true });
    errdefer af.deinit(io);
    var buf: [4096]u8 = undefined;
    var w = af.file.writer(io, &buf);
    try w.interface.writeAll(data);
    try w.interface.flush();
    try af.replace(io);
}''',
    zig_test='''const std = @import("std");

fn writeBytes(io: std.Io, dir: *std.Io.Dir, sub_path: []const u8, data: []const u8) !void {
    try dir.writeFile(io, .{ .sub_path = sub_path, .data = data, .flags = .{ .truncate = true } });
}

test "trunca contenido previo mas largo" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try writeBytes(io, &tmp.dir, "f", "contenido-largo");
    try writeBytes(io, &tmp.dir, "f", "corto");
    const got = try tmp.dir.readFileAlloc(io, "f", std.testing.allocator, .limited(64));
    defer std.testing.allocator.free(got);
    try std.testing.expectEqualStrings("corto", got);
}

test "escritura atomica reemplaza" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try writeBytes(io, &tmp.dir, "g", "previo-mas-largo");
    var af = try tmp.dir.createFileAtomic(io, "g", .{ .replace = true });
    errdefer af.deinit(io);
    var buf: [256]u8 = undefined;
    var w = af.file.writer(io, &buf);
    try w.interface.writeAll("nuevo");
    try w.interface.flush();
    try af.replace(io);
    const got = try tmp.dir.readFileAlloc(io, "g", alloc, .limited(64));
    defer alloc.free(got);
    try std.testing.expectEqualStrings("nuevo", got);
}

test "append se implementa como concat (sin O_APPEND en std)" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try writeBytes(io, &tmp.dir, "h", "a");
    const prev = try tmp.dir.readFileAlloc(io, "h", alloc, .limited(64));
    defer alloc.free(prev);
    const joined = try std.mem.concat(alloc, u8, &.{ prev, "b" });
    defer alloc.free(joined);
    try writeBytes(io, &tmp.dir, "h", joined);
    const got = try tmp.dir.readFileAlloc(io, "h", alloc, .limited(64));
    defer alloc.free(got);
    try std.testing.expectEqualStrings("ab", got);
}''',
    apis_used=["std.Io.Dir.writeFile","Io.Dir.CreateFileOptions.truncate","Io.Dir.createFileAtomic","Io.File.Atomic.replace","File.writer","File.Writer.interface"],
    constraints=["sin root","dir con permiso de escritura"],
    preconditions=["destino existe o se crea"],
    postconditions=["archivo con exactamente data"],
    side_effects=["crea/reenplaza archivo"],
    error_behavior="errores de CreateFile/WriteFile; af.deinit en errdefer limpia temporal.",
    ownership_memory="sin asignaciones salvo buffer del writer.",
    differences=["Python write_bytes no es atomico; Zig exige createFileAtomic+replace","CreateFileOptions.truncate default true en 0.16","append (>>) no esta expuesto: concatenar en memoria o escritura posicional"],
    provenance=PROV,
))

E.append(dict(
    operation_id="zig0.16/file-exists-vs-error",
    name="comprobar existencia sin ocultar errores",
    intent="Determinar si una ruta existe distinguiendo archivo ausente de error de acceso, sin que un permiso denegado se reporte como inexistente.",
    aliases=["Path.exists","os.path.exists","existe archivo","FileNotFound","AccessDenied","is_file"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''from pathlib import Path
p = Path("/run/wifihost/state")
p.exists()          # False tambien si AccessDenied (Python lo oculta)''',
    zig_impl='''const Exists = enum { yes, missing, inaccessible };

fn classify(io: std.Io, dir: *std.Io.Dir, sub_path: []const u8) Exists {
    dir.access(io, sub_path, .{}) catch |err| return switch (err) {
        error.FileNotFound => .missing,
        else => .inaccessible,
    };
    return .yes;
}''',
    zig_test='''const std = @import("std");

const Exists = enum { yes, missing, inaccessible };

fn classify(io: std.Io, dir: *std.Io.Dir, sub_path: []const u8) Exists {
    dir.access(io, sub_path, .{}) catch |err| return switch (err) {
        error.FileNotFound => .missing,
        else => .inaccessible,
    };
    return .yes;
}

test "existe vs ausente" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "x", .data = "" });
    try std.testing.expect(classify(io, &tmp.dir, "x") == .yes);
    try std.testing.expect(classify(io, &tmp.dir, "y") == .missing);
}''',
    apis_used=["std.Io.Dir.access","Io.Dir.AccessError","Io.AccessOptions"],
    constraints=["sin root"],
    preconditions=["dir abierto"],
    postconditions=["clasificado sin panico"],
    side_effects=[],
    error_behavior="FileNotFound => missing; AccessDenied/PermissionDenied => inaccessible (paridad parcial con Python).",
    ownership_memory="sin memoria.",
    differences=["Path.exists devuelve False ante AccessDenied; aqui se distingue .inaccessible","Zig diferencia error.IsDir / NotDir via otros calls"],
    provenance=PROV,
))

E.append(dict(
    operation_id="zig0.16/stdout-print-flush",
    name="imprimir con flush controlado",
    intent="Escribir lineas por stdout/stderr con flush explicito, de forma que la salida aparezca antes de continuar y los errores de escritura se propaguen.",
    aliases=["print","flush=True","sys.stderr.write","log a consola","print line"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''print(f"[*] {msg}", flush=True)
print(f"[x] {msg}", file=sys.stderr)''',
    zig_impl='''// buffered + flush explicito
fn out(io: std.Io, comptime fmt: []const u8, args: anytype) !void {
    var buf: [4096]u8 = undefined;
    var w = std.Io.File.stdout().writer(io, &buf);
    try w.interface.print(fmt, args);
    try w.interface.flush();
}

// stderr con el mismo contrato (buffer + flush explicito)
fn outErr(io: std.Io, comptime fmt: []const u8, args: anytype) !void {
    var buf: [4096]u8 = undefined;
    var w = std.Io.File.stderr().writer(io, &buf);
    try w.interface.print(fmt, args);
    try w.interface.flush();
}

// sin buffer (logs de servicio)
fn raw(io: std.Io, bytes: []const u8) !void {
    try std.Io.File.stdout().writeStreamingAll(io, bytes);
}''',
    zig_test='''const std = @import("std");

test "writer con flush round-tripa en archivo" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var f = try tmp.dir.createFile(io, "out.txt", .{ .truncate = true });
    defer f.close(io);
    var buf: [256]u8 = undefined;
    var w = f.writer(io, &buf);
    try w.interface.print("[*] {s} {d}", .{ "canal", 36 });
    try w.interface.flush();
    const got = try tmp.dir.readFileAlloc(io, "out.txt", alloc, .limited(256));
    defer alloc.free(got);
    try std.testing.expectEqualStrings("[*] canal 36", got);
}

test "print sin flush deja datos en buffer (se demuestra con fixed)" {
    var buf: [32]u8 = undefined;
    var w: std.Io.Writer = .fixed(&buf);
    try w.print("{d}", .{7});
    try std.testing.expectEqual(@as(usize, 1), w.end);
    try w.flush();
    try std.testing.expectEqualStrings("7", buf[0..1]);
}''',
    apis_used=["std.Io.File.stdout","std.Io.File.stderr","File.writer","File.Writer.interface","Io.Writer.fixed","File.writeStreamingAll"],
    constraints=["sin root"],
    preconditions=["io valido"],
    postconditions=["bytes escritos"],
    side_effects=["escribe en el stream"],
    error_behavior="errores de write/flush se propagan; usar catch para no morir en tuberia cerrada.",
    ownership_memory="buffer de pila del llamante.",
    differences=["print de Python siempre hace flush al salir de linea en tty; aqui flush es explicito","stderr de Python es no buffered; en Zig hay que usar writeStreamingAll o flush"],
    provenance=PROV,
))

E.append(dict(
    operation_id="zig0.16/parse-kv-config",
    name="parsear config clave=valor con comillas",
    intent="Parsear un fichero de configuracion tipo shell KEY=VALOR tolerando comentarios y valores entrecomillados, sin ejecutar codigo. Equivalente limitado de configparser (secciones no soportadas).",
    aliases=["configparser","shell config","KEY=VALUE","split('=')","scanf","env file","dotenv","ini","secciones","fico de config"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''import configparser
c = configparser.ConfigParser()
c.read_string("[s]\\nSSID=mi red\\n")''',
    zig_impl='''pub const Kv = struct { key: []const u8, val: []const u8 };

pub fn parseLineAlloc(gpa: std.mem.Allocator, line: []const u8) !?Kv {
    const t = std.mem.trim(u8, line, " \\t");
    if (t.len == 0 or t[0] == '#') return null;
    const eq = std.mem.indexOfScalar(u8, t, '=') orelse return null;
    const val = try unquoteAlloc(gpa, t[eq + 1 ..]);
    return .{ .key = std.mem.trim(u8, t[0..eq], " \\t"), .val = val };
}

/// Quita el envoltorio de bash %q: 'valor' y '' literal.
pub fn unquoteAlloc(allocator: std.mem.Allocator, s: []const u8) ![]const u8 {
    const t = std.mem.trim(u8, s, " \\t");
    if (t.len >= 2 and t[0] == '\\'' and t[t.len - 1] == '\\'') return allocator.dupe(u8, t[1 .. t.len - 1]);
    return allocator.dupe(u8, t);
}''',
    zig_test='''const std = @import("std");

pub const Kv = struct { key: []const u8, val: []const u8 };

pub fn parseLineAlloc(gpa: std.mem.Allocator, line: []const u8) !?Kv {
    const t = std.mem.trim(u8, line, " \\t");
    if (t.len == 0 or t[0] == '#') return null;
    const eq = std.mem.indexOfScalar(u8, t, '=') orelse return null;
    const val = try unquoteAlloc(gpa, t[eq + 1 ..]);
    return .{ .key = std.mem.trim(u8, t[0..eq], " \\t"), .val = val };
}

pub fn unquoteAlloc(allocator: std.mem.Allocator, s: []const u8) ![]const u8 {
    const t = std.mem.trim(u8, s, " \\t");
    if (t.len >= 2 and t[0] == '\\'' and t[t.len - 1] == '\\'') return allocator.dupe(u8, t[1 .. t.len - 1]);
    return allocator.dupe(u8, t);
}

test "lineas validas e invalidas" {
    const a = std.testing.allocator;
    try std.testing.expect((try parseLineAlloc(a, "# comentario")) == null);
    try std.testing.expect((try parseLineAlloc(a, "no-eq")) == null);
    const kv = (try parseLineAlloc(a, "  SSID = mi red  ")).?;
    defer a.free(kv.val);
    try std.testing.expectEqualStrings("SSID", kv.key);
    try std.testing.expectEqualStrings("mi red", kv.val);
    const kv2 = (try parseLineAlloc(a, "PSK=clave123")).?;
    defer a.free(kv2.val);
    try std.testing.expectEqualStrings("PSK", kv2.key);
    try std.testing.expectEqualStrings("clave123", kv2.val);
}

test "valor entrecomillado se desenvaina" {
    const a = std.testing.allocator;
    const kv = (try parseLineAlloc(a, "K='entre comillas'")).?;
    defer a.free(kv.val);
    try std.testing.expectEqualStrings("entre comillas", kv.val);
}''',
    apis_used=["std.mem.trim","std.mem.indexOfScalar","std.mem.splitScalar","Allocator.dupe"],
    constraints=["sin root","gpa"],
    preconditions=["texto en memoria"],
    postconditions=["pares clave/valor (valores owned si se duped)"],
    side_effects=[],
    error_behavior="lineas sin '=' se ignoran (null); valores entrecomillados se desenvainan.",
    ownership_memory="si se dupea, caller libera; slices prestadas mientras viva el texto.",
    differences=["configparser soporta secciones y tipos; esto es flat KEY=VALOR","python source-shell (old . conf) ejecutaba codigo: aqui no hay ejecucion"],
    provenance=PROV,
))

E.append(dict(
    operation_id="zig0.16/sleep-ms",
    name="esperar una duracion",
    intent="Dormir el hilo actual durante N milisegundos sin girar CPU, propagando cancelacion.",
    aliases=["time.sleep","sleep","delay","esperar","usleep","dormir","duracion","pausa","segundos","milisegundos","ms"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''import time
time.sleep(2.0)''',
    zig_impl='''fn sleepMs(io: std.Io, ms: i64) !void {
    try std.Io.sleep(io, .fromMilliseconds(ms), .real);
}
// reloj monotono no sirve para deadlines de calendario; .real para esperas''',
    zig_test='''const std = @import("std");

fn sleepMs(io: std.Io, ms: i64) !void {
    try std.Io.sleep(io, .fromMilliseconds(ms), .real);
}

test "duerme sin error" {
    try sleepMs(std.testing.io, 20);
    const d: std.Io.Duration = .fromMilliseconds(1500);
    try std.testing.expect(d.nanoseconds > 0);
}

test "duracion cero es inmediata" {
    try sleepMs(std.testing.io, 0);
}''',
    apis_used=["std.Io.sleep","std.Io.Duration.fromMilliseconds","Io.Clock"],
    constraints=["sin root"],
    preconditions=["io valido"],
    postconditions=["retorna al expirar o error"],
    side_effects=["bloquea el hilo"],
    error_behavior="error.Timeout solo si se usa deadline; Cancelable en cancelacion.",
    ownership_memory="sin memoria.",
    differences=["std.time.sleep ya no existe en 0.16: usar std.Io.sleep con Duration","Python sleep acepta float; Zig usa enteros de ns/ms"],
    provenance=PROV,
))

E.append(dict(
    operation_id="zig0.16/string-split-strip-format",
    name="dividir, recortar y formatear cadenas",
    intent="Partir una cadena por un separador descartando vacios, recortar espacios y formatear valores en un buffer tamano fijo sin asignar.",
    aliases=["split(sep)","strip()","f-string","format()","str.join","rsplit","particion"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''"a, b ,, c".split(",")             # ['a',' b ','',' c']
[x.strip() for x in _]
f"{mac:<18} {ip:<15}"''',
    zig_impl='''// recoleccion sin asignacion del llamante salvo la lista
fn collectNonEmpty(gpa: std.mem.Allocator, text: []const u8, sep: u8) ![][]const u8 {
    var list: std.ArrayList([]const u8) = .empty;
    var it = std.mem.splitScalar(u8, text, sep);
    while (it.next()) |tok| {
        const t = std.mem.trim(u8, tok, " \\t");
        if (t.len > 0) try list.append(gpa, t);
    }
    return list.toOwnedSlice(gpa);
}

fn formatInto(buf: []u8, comptime fmt: []const u8, args: anytype) ![]const u8 {
    return std.fmt.bufPrint(buf, fmt, args);   // {s:<18} = pad izquierdo
}

/// Relleno a la izquierda con `width` (equivalente a f"{text:<width}") y cola.
fn formatPadded(buf: []u8, text: []const u8, width: usize, tail: []const u8) ![]const u8 {
    return std.fmt.bufPrint(buf, "{[text]s:<[width]}{[tail]s}", .{ .text = text, .width = width, .tail = tail });
}''',
    zig_test='''const std = @import("std");

fn collectNonEmpty(gpa: std.mem.Allocator, text: []const u8, sep: u8) ![][]const u8 {
    var list: std.ArrayList([]const u8) = .empty;
    defer list.deinit(gpa);
    var it = std.mem.splitScalar(u8, text, sep);
    while (it.next()) |tok| {
        const t = std.mem.trim(u8, tok, " \\t");
        if (t.len > 0) try list.append(gpa, t);
    }
    return list.toOwnedSlice(gpa);
}

fn formatPadded(buf: []u8, text: []const u8, width: usize, tail: []const u8) ![]const u8 {
    return std.fmt.bufPrint(buf, "{[text]s:<[width]}{[tail]s}", .{ .text = text, .width = width, .tail = tail });
}

test "split descarta vacios y recorta" {
    const a = std.testing.allocator;
    const toks = try collectNonEmpty(a, "a, b ,, c", ',');
    defer a.free(toks); // tokens prestados: solo se libera la lista
    try std.testing.expectEqual(@as(usize, 3), toks.len);
    try std.testing.expectEqualStrings("b", toks[1]);
}

test "bufPrint formatea con pad" {
    var buf: [32]u8 = undefined;
    const s = try std.fmt.bufPrint(&buf, "{s:<6}|{d:0>4}", .{ "ab", 7 });
    try std.testing.expectEqualStrings("ab    |0007", s);
}

test "formatPadded rellena a la derecha hasta width" {
    var buf: [32]u8 = undefined;
    const s = try formatPadded(&buf, "ab", 6, "|ip");
    try std.testing.expectEqualStrings("ab    |ip", s);
}

test "formatPadded no trunca si ya es mas largo" {
    var buf: [32]u8 = undefined;
    const s = try formatPadded(&buf, "abcdefgh", 3, "|ip");
    try std.testing.expectEqualStrings("abcdefgh|ip", s);
}''',
    apis_used=["std.mem.splitScalar","std.mem.trim","std.fmt.bufPrint","ArrayList.append","ArrayList.toOwnedSlice"],
    constraints=["sin root","gpa"],
    preconditions=["texto valido UTF-8/bytes"],
    postconditions=["tokens no vacios recortados"],
    side_effects=[],
    error_behavior="bufPrint error.NoSpaceLeft si no cabe.",
    ownership_memory="lista owned; tokens prestados del texto original (liberar solo la lista).",
    differences=["split de Python mantiene vacios; aqui se descartan con trim+len>0","f-strings no existen: bufPrint con {s:<N} y {d:0>N}"],
    provenance=PROV,
))

E.append(dict(
    operation_id="zig0.16/spawn-redirect-child",
    name="lanzar hijo con salida redirigida a archivo",
    intent="Lanzar un proceso hijo con stdout y stderr redirigidos a un archivo (append),stdin ignorado, y esperar su codigo de salida.",
    aliases=["Popen","start_new_session","redirect stderr","stdout=archivo",">> log 2>&1","background daemon","setsid"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''import subprocess
with open(log, "ab") as f:
    p = subprocess.Popen(["hostapd", conf], stdout=f, stderr=f, stdin=subprocess.DEVNULL, start_new_session=True)
    return p.pid''',
    zig_impl='''// hostapd u otro demonio: spawn y esperar (o dejar huérfano a init)
fn spawnRedirected(io: std.Io, dir: *std.Io.Dir, log_sub: []const u8, argv: []const []const u8) !std.process.Child {
    var logf = try dir.createFile(io, log_sub, .{ .truncate = false });
    // append real: createFile(.truncate=false) deja el fd al principio, hay
    // que carriedarlo al final para que el hijo ANADE y no sobrescriba.
    const end = try logf.length(io);
    {
        var seek_buf: [1]u8 = undefined;
        var w = logf.writerStreaming(io, &seek_buf);
        try w.seekTo(end);
    }
    // nota: el hijo recibe el fd; cerrar la copia del padre tras spawn
    const child = try std.process.spawn(io, .{
        .argv = argv,
        .stdin = .ignore,
        .stdout = .{ .file = logf },
        .stderr = .{ .file = logf },
    });
    logf.close(io);
    return child;
}
// const term = try child.wait(io);  // term.exited / term.signal''',
    zig_test='''const std = @import("std");

fn spawnRedirected(io: std.Io, dir: *std.Io.Dir, log_sub: []const u8, argv: []const []const u8) !std.process.Child {
    var logf = try dir.createFile(io, log_sub, .{ .truncate = false });
    const end = try logf.length(io);
    {
        var seek_buf: [1]u8 = undefined;
        var w = logf.writerStreaming(io, &seek_buf);
        try w.seekTo(end);
    }
    const child = try std.process.spawn(io, .{
        .argv = argv,
        .stdin = .ignore,
        .stdout = .{ .file = logf },
        .stderr = .{ .file = logf },
    });
    logf.close(io);
    return child;
}

test "hijo redirigido escribe y su exit code se ve" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    var logf = try tmp.dir.createFile(io, "out.log", .{ .truncate = true });
    var child = try std.process.spawn(io, .{
        .argv = &.{ "sh", "-c", "echo spawn-ok; exit 7" },
        .stdin = .ignore,
        .stdout = .{ .file = logf },
        .stderr = .{ .file = logf },
    });
    logf.close(io);
    const term = try child.wait(io);
    try std.testing.expect(term == .exited);
    try std.testing.expectEqual(@as(u8, 7), term.exited);
    const got = try tmp.dir.readFileAlloc(io, "out.log", alloc, .limited(256));
    defer alloc.free(got);
    try std.testing.expect(std.mem.indexOf(u8, got, "spawn-ok") != null);
}

test "el log se ANADE: el contenido previo no se pisa" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "app.log", .data = "PRE" });
    var child = try spawnRedirected(io, &tmp.dir, "app.log", &.{ "sh", "-c", "printf POST" });
    const term = try child.wait(io);
    try std.testing.expect(term == .exited);
    const got = try tmp.dir.readFileAlloc(io, "app.log", alloc, .limited(256));
    defer alloc.free(got);
    try std.testing.expectEqualStrings("PREPOST", got);
}''',
    apis_used=["std.process.spawn","std.process.Child.wait","Child.SpawnOptions.StdIo.file","Io.Dir.createFile","File.close"],
    constraints=["sin root","binary accesible"],
    preconditions=["archivo de log abierto/append"],
    postconditions=["exit code conocido; salida en el archivo"],
    side_effects=["crea proceso","escribe archivo"],
    error_behavior="errores de spawn; term.signal si muere por senal.",
    ownership_memory="File se cierra tras spawn (el hijo conserva su fd).",
    differences=["start_new_session de Python hace setsid; Zig 0.16 spawn no expone setsid: para demonio real usar sh -c 'setsid x &' o pgid del SpawnOptions"],
    provenance=PROV,
))

E.append(dict(
    operation_id="zig0.16/env-var-read",
    name="leer variable de entorno",
    intent="Consultar el valor de una variable de entorno devolviendo null si no existe, sin copiar cuando no hace falta.",
    aliases=["os.environ","os.getenv","getenv","variable de entorno","PATH"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''import os
os.environ.get("WIFIHOST_LOG")
os.getenv("HOME", "/tmp")''',
    zig_impl='''// desde main(init): init.environ_map.get("WIFIHOST_LOG")
// sin Init (tests/lib): Environ explicito
fn getEnv(environ: std.process.Environ, key: []const u8) ?[:0]const u8 {
    return std.process.Environ.getPosix(environ, key);
}''',
    zig_test='''const std = @import("std");

fn getEnv(environ: std.process.Environ, key: []const u8) ?[:0]const u8 {
    return std.process.Environ.getPosix(environ, key);
}

test "lee PATH y ausente da null" {
    try std.testing.expect(getEnv(std.testing.environ, "PATH") != null);
    try std.testing.expect(getEnv(std.testing.environ, "PYZIG_AUSENTE_XYZ") == null);
}''',
    apis_used=["std.process.Environ.getPosix","std.process.Init.environ_map","Environ.Map.get"],
    constraints=["sin root"],
    preconditions=["environ del proceso"],
    postconditions=["slice prestado del bloque de environ"],
    side_effects=[],
    error_behavior="null si ausente; nohay excepciones.",
    ownership_memory="sin asignacion; el slice vive mientras viva environ.",
    differences=["os.environ de Python es un mapa mutable; aqui environ es de solo lectura salvo createMap/getAlloc","std.os.environ global ya no existe en 0.16"],
    provenance=PROV,
))

E.append(dict(
    operation_id="zig0.16/sha256-bytes",
    name="calcular sha256 de bytes",
    intent="Calcular el digest SHA-256 de un buffer para verificar integridad o identificar contenido.",
    aliases=["hashlib.sha256","sha256sum","digest","checksum","integridad"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''import hashlib
hashlib.sha256(b"abc").hexdigest()''',
    zig_impl='''pub fn sha256Bytes(data: []const u8) [32]u8 {
    var out: [32]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(data, &out, .{});
    return out;
}

pub fn sha256Hex(data: []const u8) [64]u8 {
    const digest = sha256Bytes(data);
    return std.fmt.bytesToHex(digest, .lower);
}''',
    zig_test='''const std = @import("std");

pub fn sha256Bytes(data: []const u8) [32]u8 {
    var out: [32]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(data, &out, .{});
    return out;
}

pub fn sha256Hex(data: []const u8) [64]u8 {
    const digest = sha256Bytes(data);
    return std.fmt.bytesToHex(digest, .lower);
}

test "sha256 de abc coincide con el valor conocido" {
    try std.testing.expectEqualStrings(
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        &sha256Hex("abc"),
    );
}

test "sha256 de la cadena vacia" {
    try std.testing.expectEqualStrings(
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        &sha256Hex(""),
    );
}''',
    apis_used=["std.crypto.hash.sha2.Sha256.hash","std.fmt.fmtSliceHexLower","std.fmt.bufPrint"],
    constraints=["sin root"],
    preconditions=["datos en memoria"],
    postconditions=["digest de 32 bytes"],
    side_effects=[],
    error_behavior="hash es total (no falla); bufPrint puede fallar por espacio.",
    ownership_memory="buffers de pila.",
    differences=["hexdigest(): fmtSliceHexLower + bufPrint","para streaming: Sha256.init/update/final"],
    provenance=PROV,
))

E.append(dict(
    operation_id="zig0.16/detached-daemon-no-shell",
    name="demonio desacoplado sin shell (NO DEMOSTRADO)",
    intent="Arrancar un proceso que sobreviva al padre y quede en su propia sesion, sin depender de un shell externo, equivalente exacto de start_new_session/setsid.",
    aliases=["setsid","daemonize","doble fork","start_new_session","nohup","detach"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref='''subprocess.Popen([...], start_new_session=True)  # el hijo sigue vivo tras exit del padre''',
    zig_impl='''// Zig 0.16 std.process.spawn NO expone setsid ni doble-fork.
// Opciones: (a) pgid en SpawnOptions (no crea sesion nueva),
//           (b) shell out: sh -c 'setsid hostapd ... >> log 2>&1 &',
//           (c) fork+setsid manual con std.posix (no portable).
// NO verificado en gate: un hijo que sobreviva al padre. Requiere prueba
// dedicada con marcador de vida tras exit del padre.''',
    zig_test=None,
    apis_used=["std.process.spawn","std.process.SpawnOptions.pgid","std.posix.setsid"],
    constraints=["requiere decision de portabilidad"],
    preconditions=["proceso largo"],
    postconditions=["N/D"],
    side_effects=["proceso persiste"],
    error_behavior="N/D",
    ownership_memory="N/D",
    differences=["setsid es llamado Linux no envuelto por std","popen(start_new_session) de Python si lo hace"],
    provenance="NO_GATE: no se ejecuta prueba; evidencia insuficiente",
    status="NOT_DEMONSTRATED",
    entry_type="gap",
))

# ---- validacion + escritura (unico escritor: pyzig.corpus) ----------------
out = ROOT / "corpus" / "pyzig.corpus.jsonl"
REQ = ["operation_id","name","intent","aliases","source_lang","target_lang","zig_version","python_version","platform","py_ref","zig_impl","apis_used","constraints","provenance"]

seen = set()
for e in E:
    for k in REQ:
        if k not in e:
            sys.exit(f"FALTA {k} en {e.get('operation_id','?')}")
    e.setdefault("platform", "linux")
    e.setdefault("tests", [{"name": "zig test gate", "kind": "zig-test"}] if e.get("zig_test") else [])
    e.setdefault("differences", [])
    e.setdefault("preconditions", [])
    e.setdefault("postconditions", [])
    e.setdefault("side_effects", [])
    e.setdefault("error_behavior", "")
    e.setdefault("ownership_memory", "")
    e.setdefault("evidence", {"status": e.get("status", "UNVERIFIED"), "runs": []})
    e.setdefault("entry_type", "recipe")
    # contrato de fuzzing (esquema, driver, modelo, campos comparados, tipo)
    contract = contracts.contract_for(e["operation_id"])
    e["fuzz"] = contract
    e["type_signature"] = contract["type_signature"]
    if e["operation_id"] in seen:
        sys.exit(f"DUPLICADO {e['operation_id']}")
    seen.add(e["operation_id"])

written = corpus_mod.write_all(E, path=out, preserve_evidence=True)
problems = corpus_mod.verify_chain(out)
for p in problems:
    print(f"AVISO {p}", file=sys.stderr)
print(f"corpus: {out} entradas={len(written)}")
