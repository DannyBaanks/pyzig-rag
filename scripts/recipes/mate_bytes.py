"""Recetas de numeros y bytes (area mate_bytes). Verificado con zig test 0.16.0.

Cubre el camino Python -> Zig de: formateo de cadenas, valores especiales de
coma flotante, empaquetado binario, conversion entero<->bytes, division/resto
con negativos, conteo de bits, redondeo y cadenas C terminadas en NUL.

`error_signatures` son lineas `error: ...` REALES copiadas de ejecutar
`zig test` 0.16.0 sobre el codigo roto (sin ruta ni posicion)."""
from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"; PY = "3.12"; PROV = "std local de zig 0.16.0 (repo en lib/std); errores copiados de `zig test` 0.16.0"

ENTRIES = [
# ---------------------------------------------------------------- allocPrint
dict(
    operation_id="zig0.16/format-string-alloc-print",
    name="construir texto con formato (f-string / str.format)",
    intent="Interpolar variables y numeros en un texto como una f-string o str.format de Python, asignando el resultado o escribiendolo en un buffer del llamador.",
    aliases=["f-string","str.format","format() de Python","interpolar variables en un texto","construir texto con placeholders","formatear enteros y texto","concatenar texto y numeros","std.fmt.allocPrint","std.fmt.bufPrint","formatear con ancho y relleno","%s %d","plantilla de texto con valores","string format Zig"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''name, n = "Ana", 3
f"hola {name}, tienes {n} mensajes"          # 'hola Ana, tienes 3 mensajes'
"{0}-{1:04d}-{2:.2f}".format(7, 42, 3.14159) # '7-0042-3.14'
f"{42:>5}"                                   # '   42'
f"{42:04d}"                                  # '0042'
f"{255:#x}"                                  # '0xff'
"%s=%d" % ("x", 9)                           # 'x=9' ''',
    zig_impl=r'''pub fn greetAlloc(allocator: std.mem.Allocator, name: []const u8, n: u32) ![]u8 {
    // allocPrint asigna: el llamador libera con allocator.free
    return std.fmt.allocPrint(allocator, "hola {s}, tienes {d} mensajes", .{ name, n });
}

pub fn greetBuf(buf: []u8, name: []const u8, n: u32) ![]u8 {
    // bufPrint no asigna: escribe en buf y devuelve el slice usado
    return std.fmt.bufPrint(buf, "hola {s}, tienes {d} mensajes", .{ name, n });
}
// ancho/relleno: {d:>5} y {d:0>4}; hex: {x}; decimales: {d:.2}''',
    zig_test=r'''const std = @import("std");

pub fn greetAlloc(allocator: std.mem.Allocator, name: []const u8, n: u32) ![]u8 {
    return std.fmt.allocPrint(allocator, "hola {s}, tienes {d} mensajes", .{ name, n });
}

pub fn greetBuf(buf: []u8, name: []const u8, n: u32) ![]u8 {
    return std.fmt.bufPrint(buf, "hola {s}, tienes {d} mensajes", .{ name, n });
}

test "allocPrint basico" {
    const a = std.testing.allocator;
    const s = try greetAlloc(a, "Ana", 3);
    defer a.free(s);
    try std.testing.expectEqualStrings("hola Ana, tienes 3 mensajes", s);
}

test "bufPrint sin asignar y NoSpaceLeft" {
    var buf: [64]u8 = undefined;
    try std.testing.expectEqualStrings("hola Ana, tienes 3 mensajes", try greetBuf(&buf, "Ana", 3));
    var tiny: [4]u8 = undefined;
    try std.testing.expectError(error.NoSpaceLeft, greetBuf(&tiny, "Ana", 3));
}

test "format ancho, relleno, hex y decimales" {
    var buf: [64]u8 = undefined;
    try std.testing.expectEqualStrings("   42", try std.fmt.bufPrint(&buf, "{d:>5}", .{42}));
    try std.testing.expectEqualStrings("0042", try std.fmt.bufPrint(&buf, "{d:0>4}", .{42}));
    try std.testing.expectEqualStrings("ff", try std.fmt.bufPrint(&buf, "{x}", .{255}));
    try std.testing.expectEqualStrings("0xff", try std.fmt.bufPrint(&buf, "0x{x}", .{255}));
    try std.testing.expectEqualStrings("3.14", try std.fmt.bufPrint(&buf, "{d:.2}", .{3.14159}));
}''',
    apis_used=["std.fmt.allocPrint","std.fmt.bufPrint","std.mem.Allocator","{s}","{d}","{x}","{d:.2}","{d:0>4}"],
    constraints=["sin root","allocator explicito en allocPrint","formato en comptime"],
    preconditions=["el formato es un literal conocido en comptime"],
    postconditions=["allocPrint devuelve un slice propio del allocator","bufPrint devuelve un slice dentro de buf"],
    side_effects=[],
    error_behavior="allocPrint: error.OutOfMemory. bufPrint: error.NoSpaceLeft si el buffer no cabe. Ambas funciones no pueden fallar por formato: el formato se valida al compilar.",
    ownership_memory="allocPrint asigna y el llamador libera con allocator.free; bufPrint no asigna y el slice devuelto apunta a buf (no liberar).",
    differences=["bufPrint no asigna nada (equivalente a escribir en un bytearray precalculado); allocPrint es el equivalente directo de una f-string cuando el tamano no se conoce de antemano","el formato es comptime: los argumentos y el numero de ellos se comprueban al compilar; Python acepta cualquier objeto con __format__","Zig exige especificador para un slice ({s}); un '{}' con un []const u8 no compila (Python si)",
                    "no hay placeholders con nombre ({name}); los argumentos son posicionales y se referencian con {0}, {1} o en orden","las specs de Python no tienen traduccion uno a uno: existen ancho/alineacion/relleno y precision, pero no '#' ni el formato '%' estilo printf","{d:.N} redondea distinto que Python en empates (ver parse-float-format-decimals); para dinero usar enteros o una rutina propia"],
    error_signatures=["error: expected 3 argument(s), found 2",
                      "error: cannot format slice without a specifier (i.e. {s}, {x}, {b64}, or {any})"],
    provenance=PROV,
),
# ---------------------------------------------------------------- isInf/isNan
dict(
    operation_id="zig0.16/float-special-values-isinf-isnan",
    name="infinito, NaN y comprobaciones de float especial",
    intent="Comprobar si un float es infinito, NaN o finito y producir los valores inf/-inf/nan, como math.isinf, math.isnan, math.inf y math.nan de Python.",
    aliases=["math.isinf","math.isnan","math.inf","math.nan","float('inf')","float('nan')","comprobar si un float es infinito","detectar NaN","valor no finito","std.math.isInf","std.math.isNan","std.math.isFinite","std.math.inf","std.math.nan","infinito negativo","not a number"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''import math
math.isinf(float("inf"))    # True
math.isinf(float("-inf"))   # True
math.isnan(float("nan"))    # True
math.isinf(1.0)             # False
math.isnan(float("inf"))    # False
math.isfinite(float("inf")) # False
math.inf, -math.inf, math.nan
x = float("nan")
x == x                      # False: NaN nunca es igual a si mismo''',
    zig_impl=r'''pub fn isInf(x: f64) bool { return std.math.isInf(x); }        // +inf y -inf
pub fn isPosInf(x: f64) bool { return std.math.isPositiveInf(x); }
pub fn isNegInf(x: f64) bool { return std.math.isNegativeInf(x); }
pub fn isNan(x: f64) bool { return std.math.isNan(x); }
pub fn isFinite(x: f64) bool { return std.math.isFinite(x); }

pub fn inf() f64 { return std.math.inf(f64); }      // math.inf
pub fn nan() f64 { return std.math.nan(f64); }      // math.nan''',
    zig_test=r'''const std = @import("std");

pub fn isInf(x: f64) bool {
    return std.math.isInf(x);
}
pub fn isPosInf(x: f64) bool {
    return std.math.isPositiveInf(x);
}
pub fn isNegInf(x: f64) bool {
    return std.math.isNegativeInf(x);
}
pub fn isNan(x: f64) bool {
    return std.math.isNan(x);
}
pub fn isFinite(x: f64) bool {
    return std.math.isFinite(x);
}
pub fn inf() f64 {
    return std.math.inf(f64);
}
pub fn negInf() f64 {
    return -std.math.inf(f64);
}
pub fn nan() f64 {
    return std.math.nan(f64);
}

test "isinf/isnan" {
    try std.testing.expect(isInf(inf()));
    try std.testing.expect(isInf(negInf()));
    try std.testing.expect(!isInf(nan()));
    try std.testing.expect(!isInf(1.0));
    try std.testing.expect(isNan(nan()));
    try std.testing.expect(isNan(-nan()));
    try std.testing.expect(!isNan(inf()));
    try std.testing.expect(!isNan(1.0));
}

test "signo del infinito" {
    try std.testing.expect(isPosInf(inf()));
    try std.testing.expect(!isPosInf(negInf()));
    try std.testing.expect(isNegInf(negInf()));
    try std.testing.expect(!isNegInf(inf()));
    try std.testing.expect(!isPosInf(nan()));
}

test "finito" {
    try std.testing.expect(!isFinite(inf()));
    try std.testing.expect(!isFinite(nan()));
    try std.testing.expect(isFinite(1.0));
    try std.testing.expect(isFinite(-0.0));
}

test "inf/nan producibles y comparables" {
    try std.testing.expectEqual(std.math.inf(f64), inf());
    try std.testing.expect(inf() > 1e308);
    try std.testing.expect(negInf() < -1e308);
    // NaN no es igual a si mismo: hay que usar isNan, no ==
    try std.testing.expect(!(nan() == nan()));
}

test "f32 y f16" {
    const x: f32 = std.math.inf(f32);
    try std.testing.expect(std.math.isInf(x));
    try std.testing.expect(std.math.isNan(std.math.nan(f32)));
    const h: f16 = std.math.nan(f16);
    try std.testing.expect(std.math.isNan(h));
}

test "parseFloat acepta inf/-inf/nan" {
    try std.testing.expect(isInf(try std.fmt.parseFloat(f64, "inf")));
    try std.testing.expect(isNegInf(try std.fmt.parseFloat(f64, "-inf")));
    try std.testing.expect(isNan(try std.fmt.parseFloat(f64, "nan")));
}''',
    apis_used=["std.math.isInf","std.math.isPositiveInf","std.math.isNegativeInf","std.math.isNan","std.math.isFinite","std.math.inf","std.math.nan"],
    constraints=["sin root","tipo float explicito (f16/f32/f64/...)"],
    preconditions=["float IEEE-754"],
    postconditions=["isInf cubre ambos signos","isNan es la unica comprobacion fiable de NaN"],
    side_effects=[],
    error_behavior="no fallan: son predicados sobre la representacion IEEE-754. Comparar con == no detecta NaN.",
    ownership_memory="sin asignacion; todo son valores.",
    differences=["math.inf/math.nan son valores en Python; en Zig std.math.inf(T)/nan(T) son funciones que reciben el tipo","isInf(x) incluye +inf y -inf; isPositiveInf/isNegativeInf distinguen el signo (equivalente a comparar con math.inf)","Python solo tiene isinf/isnan/isfinite; Zig anade isSignalNan y isPositiveInf/isNegativeInf","no fiarse de == para NaN: nan == nan es false en ambos; usar isNan","construir inf/nan dividiendo por cero (1.0/0.0) es error en comptime: usar std.math.inf/nan"],
    error_signatures=["error: root source file struct 'math' has no member named 'isinf'",
                      "error: expected type 'f64', found 'fn (comptime type) callconv(.@\"inline\") anytype'"],
    provenance=PROV,
),
# ---------------------------------------------------------------- struct.pack
dict(
    operation_id="zig0.16/struct-pack-endian-readint",
    name="struct.pack/unpack de enteros con endian",
    intent="Empaquetar un entero en N bytes con orden big o little endian y desempaquetarlo de vuelta, como struct.pack('<I', x) y struct.unpack('>H', b)[0].",
    aliases=["struct.pack","struct.unpack","empaquetar entero en bytes","desempaquetar bytes a entero","little endian","big endian","network byte order","std.mem.writeInt","std.mem.readInt","readInt slice","u32 a 4 bytes","short buffer","pack '<I'","pack '>H'","leer entero de un buffer en un offset"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''import struct
struct.pack("<I", 0x01020304)                       # b'\x04\x03\x02\x01'
struct.pack(">I", 0x01020304)                       # b'\x01\x02\x03\x04'
struct.pack(">H", 0xBEEF)                           # b'\xbe\xef'
struct.unpack("<I", b"\x04\x03\x02\x01")[0]         # 16909060
struct.unpack(">i", b"\xff\xff\xff\xfe")[0]         # -2
struct.pack(">i", -2)                               # b'\xff\xff\xff\xfe'
struct.unpack(">I", b"\x01\x02")                    # struct.error: requires a buffer of 4 bytes''',
    zig_impl=r'''// writeInt escribe en *[N]u8; readInt lee de *const [N]u8 (NO de un slice).
pub fn packU32(out: *[4]u8, v: u32, endian: std.builtin.Endian) void {
    std.mem.writeInt(u32, out, v, endian);
}

pub fn unpackU32(bytes: *const [4]u8, endian: std.builtin.Endian) u32 {
    return std.mem.readInt(u32, bytes, endian);
}

// desde un slice con offset: bytes[off..][0..4] coacciona a *const [4]u8
pub fn u32At(bytes: []const u8, offset: usize, endian: std.builtin.Endian) !u32 {
    if (offset + 4 > bytes.len) return error.ShortBuffer;
    const chunk: *const [4]u8 = bytes[offset..][0..4];
    return std.mem.readInt(u32, chunk, endian);
}''',
    zig_test=r'''const std = @import("std");

pub fn packU32(out: *[4]u8, v: u32, endian: std.builtin.Endian) void {
    std.mem.writeInt(u32, out, v, endian);
}

pub fn unpackU32(bytes: *const [4]u8, endian: std.builtin.Endian) u32 {
    return std.mem.readInt(u32, bytes, endian);
}

pub fn packU16(out: *[2]u8, v: u16) void {
    std.mem.writeInt(u16, out, v, .big);
}

pub fn unpackI32(bytes: *const [4]u8, endian: std.builtin.Endian) i32 {
    return std.mem.readInt(i32, bytes, endian);
}

pub fn u32At(bytes: []const u8, offset: usize, endian: std.builtin.Endian) !u32 {
    if (offset + 4 > bytes.len) return error.ShortBuffer;
    const chunk: *const [4]u8 = bytes[offset..][0..4];
    return std.mem.readInt(u32, chunk, endian);
}

pub fn putU32At(buf: []u8, offset: usize, v: u32, endian: std.builtin.Endian) !void {
    if (offset + 4 > buf.len) return error.ShortBuffer;
    std.mem.writeInt(u32, buf[offset..][0..4], v, endian);
}

test "struct.pack '<I' y '>I'" {
    var out: [4]u8 = undefined;
    packU32(&out, 0x01020304, .little);
    try std.testing.expectEqualSlices(u8, &.{ 0x04, 0x03, 0x02, 0x01 }, &out);
    packU32(&out, 0x01020304, .big);
    try std.testing.expectEqualSlices(u8, &.{ 0x01, 0x02, 0x03, 0x04 }, &out);
}

test "struct.unpack con ambos endian" {
    const be = [_]u8{ 0x01, 0x02, 0x03, 0x04 };
    try std.testing.expectEqual(@as(u32, 16909060), unpackU32(&be, .big));
    try std.testing.expectEqual(@as(u32, 67305985), unpackU32(&be, .little));
}

test "struct.pack '>H' y '>i'" {
    var h: [2]u8 = undefined;
    packU16(&h, 0xbeef);
    try std.testing.expectEqualSlices(u8, &.{ 0xbe, 0xef }, &h);
    const neg: [4]u8 = .{ 0xff, 0xff, 0xff, 0xfe };
    try std.testing.expectEqual(@as(i32, -2), unpackI32(&neg, .big));
}

test "leer y escribir en un offset de un slice" {
    const buf = [_]u8{ 0xaa, 0x01, 0x02, 0x03, 0x04, 0xbb };
    try std.testing.expectEqual(@as(u32, 0x01020304), try u32At(&buf, 1, .big));
    try std.testing.expectError(error.ShortBuffer, u32At(&buf, 3, .big));
    var w: [8]u8 = @splat(0);
    try putU32At(&w, 2, 0xdeadbeef, .big);
    try std.testing.expectEqualSlices(u8, &.{ 0, 0, 0xde, 0xad, 0xbe, 0xef, 0, 0 }, &w);
}

test "tamano exacto: u16 necesita 2 bytes" {
    const two = [_]u8{ 0x12, 0x34 };
    try std.testing.expectEqual(@as(u16, 0x1234), std.mem.readInt(u16, &two, .big));
    const one = [_]u8{0x12};
    try std.testing.expectEqual(@as(u8, 0x12), std.mem.readInt(u8, &one, .big));
}''',
    apis_used=["std.mem.readInt","std.mem.writeInt","std.builtin.Endian","std.testing.expectEqualSlices"],
    constraints=["sin root","tamano N fijo en comptime (N = bits/8)","buffer alineado a 1 basta: readInt no exige alineacion natural"],
    preconditions=["bytes.len >= offset + N al leer de un slice (validar antes)"],
    postconditions=["readInt devuelve el entero con el endian pedido","writeInt deja exactamente N bytes"],
    side_effects=[],
    error_behavior="readInt/writeInt no fallan; fuera de rango es UB: validar offset+4 <= len y devolver error.ShortBuffer (no hay struct.error).",
    ownership_memory="sin asignacion; se escribe en un array del llamador. readInt toma *const [N]u8 y writeInt *[N]u8.",
    differences=["readInt NO acepta un slice: recibe *const [N]u8; con un slice de longitud runtime hay que escribir bytes[off..][0..4] (no basta bytes[off..off+4] si la longitud no es comptime)","el endian es un argumento explicito (.big/.little) en cada llamada; no hay format string '<'/'>'","struct.pack admite varios campos y offsets; en Zig se empaqueta campo a campo","no hay struct.error: la longitud se valida a mano (aqui error.ShortBuffer)","@byteSwap opera sobre enteros, no sobre el array de bytes: aplicarlo al buffer no compila","no confundir con @bitCast: writeInt fija el orden de bytes, @bitCast usa el orden nativo y exige tamano y alineacion"],
    error_signatures=["error: expected type '*const [4]u8', found '[]const u8'",
                      "error: expected integer or vector, found '[4]u8'",
                      "error: evaluation exceeded 1000 backwards branches"],
    provenance=PROV,
),
# ---------------------------------------------------------------- from_bytes
dict(
    operation_id="zig0.16/int-from-bytes-to-bytes-endian",
    name="entero a bytes y bytes a entero (from_bytes / to_bytes)",
    intent="Convertir un entero de ancho fijo a su representacion en bytes y volver, con orden big o little endian y con signo (complemento a dos), como int.to_bytes e int.from_bytes.",
    aliases=["int.from_bytes","int.to_bytes","from_bytes","to_bytes","entero a bytes","bytes a entero","signed=True","big endian y little endian","complemento a dos","convertir 8 bytes a numero","uint64 desde bytes","std.mem.readInt endian","serializar entero en binario"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''int.from_bytes(b"\x01\x02\x03\x04", "big")                  # 16909060
int.from_bytes(b"\x01\x02\x03\x04", "little")               # 67305985
int.from_bytes(b"\xff\xff\xff\xfe", "big", signed=True)     # -2
(16909060).to_bytes(4, "big")                               # b'\x01\x02\x03\x04'
(16909060).to_bytes(4, "little")                            # b'\x04\x03\x02\x01'
(-2).to_bytes(4, "big", signed=True)                        # b'\xff\xff\xff\xfe'
(1).to_bytes(8, "big")                                      # b'\x00...\x01'
(300).to_bytes(1, "big")                                    # OverflowError: int too big to convert''',
    zig_impl=r'''// T fija el ancho: @sizeOf(T) bytes. Usar u64/i64 para 8 bytes.
pub fn toBytes(comptime T: type, value: T, endian: std.builtin.Endian, out: *[@sizeOf(T)]u8) void {
    std.mem.writeInt(T, out, value, endian);
}

pub fn fromBytes(comptime T: type, bytes: *const [@sizeOf(T)]u8, endian: std.builtin.Endian) T {
    return std.mem.readInt(T, bytes, endian);
}
// u32/i32 -> 4 bytes; u64/i64 -> 8 bytes; iN usa complemento a dos.''',
    zig_test=r'''const std = @import("std");

pub fn toBytes(comptime T: type, value: T, endian: std.builtin.Endian, out: *[@sizeOf(T)]u8) void {
    std.mem.writeInt(T, out, value, endian);
}

pub fn fromBytes(comptime T: type, bytes: *const [@sizeOf(T)]u8, endian: std.builtin.Endian) T {
    return std.mem.readInt(T, bytes, endian);
}

test "int.to_bytes big y little" {
    var out: [4]u8 = undefined;
    toBytes(u32, 16909060, .big, &out);
    try std.testing.expectEqualSlices(u8, &.{ 0x01, 0x02, 0x03, 0x04 }, &out);
    toBytes(u32, 16909060, .little, &out);
    try std.testing.expectEqualSlices(u8, &.{ 0x04, 0x03, 0x02, 0x01 }, &out);
}

test "int.from_bytes big y little" {
    const be = [_]u8{ 0x01, 0x02, 0x03, 0x04 };
    try std.testing.expectEqual(@as(u32, 16909060), fromBytes(u32, &be, .big));
    try std.testing.expectEqual(@as(u32, 67305985), fromBytes(u32, &be, .little));
}

test "signed=True: complemento a dos" {
    const neg = [_]u8{ 0xff, 0xff, 0xff, 0xfe };
    try std.testing.expectEqual(@as(i32, -2), fromBytes(i32, &neg, .big));
    var out: [4]u8 = undefined;
    toBytes(i32, -2, .big, &out);
    try std.testing.expectEqualSlices(u8, &neg, &out);
}

test "ancho de 8 bytes con u64/i64" {
    var out: [8]u8 = undefined;
    toBytes(u64, 1, .big, &out);
    try std.testing.expectEqualSlices(u8, &.{ 0, 0, 0, 0, 0, 0, 0, 1 }, &out);
    try std.testing.expectEqual(@as(u64, 1), fromBytes(u64, &out, .big));
    toBytes(i64, -1, .little, &out);
    try std.testing.expectEqualSlices(u8, &.{ 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff }, &out);
    try std.testing.expectEqual(@as(i64, -1), fromBytes(i64, &out, .little));
}

test "ancho de 1 byte: u8 cubre 0..255" {
    var one: [1]u8 = undefined;
    toBytes(u8, 255, .big, &one);
    try std.testing.expectEqual(@as(u8, 255), fromBytes(u8, &one, .big));
}''',
    apis_used=["std.mem.readInt","std.mem.writeInt","std.builtin.Endian","@sizeOf"],
    constraints=["sin root","ancho fijo en el tipo T","byteorder explicito (no hay default 'big')"],
    preconditions=["bytes.len == @sizeOf(T)"],
    postconditions=["toBytes escribe exactamente @sizeOf(T) bytes","fromBytes reconstruye el valor"],
    side_effects=[],
    error_behavior="el desbordamiento de ancho no da OverflowError: en comptime no compila (300 no cabe en u8) y en runtime @intCast hace panic en modo seguro. La longitud distinta a @sizeOf(T) no compila.",
    ownership_memory="sin asignacion; el buffer es del llamador.",
    differences=["Python tiene enteros de precision arbitraria y elige el ancho al llamar (to_bytes(n)); en Zig el ancho lo fija el tipo (u32/i32/u64/i64), asi que 'n' es @sizeOf(T)","OverflowError de Python no existe como error de runtime: el overflow es error de compilacion en comptime o panic de @intCast en runtime","int.from_bytes tiene byteorder por defecto 'big' en Python <3.11 y obligatorio despues; en Zig siempre es explicito","from_bytes de Python acepta cualquier longitud; readInt exige exactamente N bytes (para longitudes variables existe std.mem.readVarInt)","signed=True se modela con T con signo (i32/i64): readInt interpreta el patron en complemento a dos"],
    error_signatures=["error: expected type '*const [4]u8', found '*const [8]u8'"],
    provenance=PROV,
),
# ---------------------------------------------------------------- div/mod
dict(
    operation_id="zig0.16/div-floor-mod-negative",
    name="// y % de Python con negativos",
    intent="Reproducir la division entera que redondea hacia abajo y el resto con el signo del divisor (// y % de Python) con numeros negativos, en vez de la division truncada.",
    aliases=["// de Python","% de Python","division entera con negativos","resto con negativos","divmod","floor division","modulo negativo","@divFloor","@mod","@divTrunc","@rem","division trunca vs floor","resto con signo del divisor","resto division signed"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''-7 // 2        # -4  (redondea hacia -infinito)
-7 % 2         # 1   (signo del divisor)
7 // -2        # -4
7 % -2         # -1
divmod(-7, 2)  # (-4, 1)
-7 / 2         # -3.5 (float en Python 3)
# La identidad: a == (a // b) * b + (a % b)
assert -7 == (-7 // 2) * 2 + (-7 % 2)''',
    zig_impl=r'''pub fn pyFloorDiv(a: i32, b: i32) i32 { return @divFloor(a, b); } // Python //
pub fn pyMod(a: i32, b: i32) i32 { return @mod(a, b); }           // Python %

pub fn pyDivmod(a: i32, b: i32) struct { q: i32, r: i32 } {
    return .{ .q = @divFloor(a, b), .r = @mod(a, b) };
}
// OJO: @divTrunc y @rem son la division truncada (C); '/' en enteros tambien trunca.''',
    zig_test=r'''const std = @import("std");

pub fn pyFloorDiv(a: i32, b: i32) i32 {
    return @divFloor(a, b);
}
pub fn pyMod(a: i32, b: i32) i32 {
    return @mod(a, b);
}
pub fn pyDivmod(a: i32, b: i32) struct { q: i32, r: i32 } {
    return .{ .q = @divFloor(a, b), .r = @mod(a, b) };
}
pub fn zigTruncDiv(a: i32, b: i32) i32 {
    return @divTrunc(a, b);
}
pub fn zigRem(a: i32, b: i32) i32 {
    return @rem(a, b);
}

test "// y % de Python con negativos" {
    try std.testing.expectEqual(@as(i32, -4), pyFloorDiv(-7, 2));
    try std.testing.expectEqual(@as(i32, 1), pyMod(-7, 2));
    try std.testing.expectEqual(@as(i32, -4), pyFloorDiv(7, -2));
    try std.testing.expectEqual(@as(i32, -1), pyMod(7, -2));
    try std.testing.expectEqual(@as(i32, 3), pyFloorDiv(7, 2));
    try std.testing.expectEqual(@as(i32, 1), pyMod(7, 2));
}

test "divmod y la identidad" {
    const r = pyDivmod(-7, 2);
    try std.testing.expectEqual(@as(i32, -4), r.q);
    try std.testing.expectEqual(@as(i32, 1), r.r);
    try std.testing.expectEqual(@as(i32, -7), r.q * 2 + r.r);
    const s = pyDivmod(7, -2);
    try std.testing.expectEqual(@as(i32, 7), s.q * -2 + s.r);
}

test "la trampa: @divTrunc y @rem NO son // y %" {
    try std.testing.expectEqual(@as(i32, -3), zigTruncDiv(-7, 2));
    try std.testing.expectEqual(@as(i32, -1), zigRem(-7, 2));
    try std.testing.expect(zigTruncDiv(-7, 2) != pyFloorDiv(-7, 2));
    try std.testing.expect(zigRem(-7, 2) != pyMod(-7, 2));
    // '/' sobre enteros tambien trunca: equivale a @divTrunc
    try std.testing.expectEqual(@as(i32, -3), @as(i32, -7) / 2);
}

test "signo del resto: @rem sigue al dividendo, @mod al divisor" {
    try std.testing.expectEqual(@as(i32, -1), @rem(@as(i32, -7), 2));
    try std.testing.expectEqual(@as(i32, 1), @mod(@as(i32, -7), 2));
    try std.testing.expectEqual(@as(i32, 1), @rem(@as(i32, 7), -2));
    try std.testing.expectEqual(@as(i32, -1), @mod(@as(i32, 7), -2));
}

test "con positivos coinciden" {
    try std.testing.expectEqual(zigTruncDiv(9, 4), pyFloorDiv(9, 4));
    try std.testing.expectEqual(zigRem(9, 4), pyMod(9, 4));
}''',
    apis_used=["@divFloor","@mod","@divTrunc","@rem"],
    constraints=["sin root","enteros con signo","b != 0"],
    preconditions=["divisor distinto de cero"],
    postconditions=["a == @divFloor(a,b) * b + @mod(a,b)","@mod tiene el signo del divisor"],
    side_effects=[],
    error_behavior="b == 0 es panic (division por cero) en modo seguro; minInt / -1 desborda y hace panic. Python lanza ZeroDivisionError y no desborda.",
    ownership_memory="sin asignacion.",
    differences=["Python // redondea hacia -infinito (@divFloor); la division truncada de C (@divTrunc y '/' en enteros Zig) redondea hacia cero: -7//2 = -4 pero -7/2 truncado = -3","Python % tiene el signo del divisor (@mod); @rem sigue el signo del dividendo: -7 % 2 = 1 pero @rem(-7,2) = -1","'/' en enteros de Zig trunca (como @divTrunc), no es la division real de Python 3 (que da float)","Python no desborda (enteros ilimitados); en Zig minInt/-1 desborda y hace panic","divmod se modela con un struct {q, r} (o con dos llamadas)"],
    error_signatures=["error: remainder division with 'i32' and 'i32': signed integers and floats must use @rem or @mod"],
    provenance=PROV,
),
# ---------------------------------------------------------------- bit ops
dict(
    operation_id="zig0.16/int-bit-count-bit-length",
    name="contar bits encendidos y bits significativos",
    intent="Contar cuantos bits a 1 tiene un entero y cuantos bits necesita para representarse, como int.bit_count() e int.bit_length().",
    aliases=["int.bit_count","int.bit_length","bit_count","bit_length","contar bits encendidos","popcount","numero de bits necesarios","@popCount","@clz","count set bits","bits que necesita un entero","leading zeros"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''(0b1011).bit_count()   # 3
(0).bit_count()         # 0
(255).bit_count()       # 8
(-3).bit_count()        # 2  (usa abs)
(255).bit_length()      # 8
(0).bit_length()        # 0
(1).bit_length()        # 1
(-1).bit_length()       # 1  (usa abs)''',
    zig_impl=r'''pub fn bitCount(x: u64) u7 {
    return @popCount(x);
}

/// bit_length de Python para u64: 0 -> 0; si no, 64 - @clz(x).
pub fn bitLength(x: u64) u7 {
    if (x == 0) return 0;
    return 64 - @clz(x);
}

/// bit_count de Python con signo: cuenta los bits de abs(x).
pub fn bitCountSigned(x: i64) u7 {
    if (x < 0) return @popCount(@as(u64, @bitCast(-x)));
    return @popCount(@as(u64, @intCast(x)));
}''',
    zig_test=r'''const std = @import("std");

pub fn bitCount(x: u64) u7 {
    return @popCount(x);
}

pub fn bitLength(x: u64) u7 {
    if (x == 0) return 0;
    return 64 - @clz(x);
}

pub fn bitCountSigned(x: i64) u7 {
    if (x < 0) return @popCount(@as(u64, @bitCast(-x)));
    return @popCount(@as(u64, @intCast(x)));
}

test "bit_count" {
    try std.testing.expectEqual(@as(u7, 3), bitCount(0b1011));
    try std.testing.expectEqual(@as(u7, 0), bitCount(0));
    try std.testing.expectEqual(@as(u7, 8), bitCount(255));
    try std.testing.expectEqual(@as(u7, 64), bitCount(std.math.maxInt(u64)));
}

test "bit_length" {
    try std.testing.expectEqual(@as(u7, 8), bitLength(255));
    try std.testing.expectEqual(@as(u7, 0), bitLength(0));
    try std.testing.expectEqual(@as(u7, 1), bitLength(1));
    try std.testing.expectEqual(@as(u7, 4), bitLength(0b1011));
    try std.testing.expectEqual(@as(u7, 64), bitLength(std.math.maxInt(u64)));
}

test "bit_count con signo (Python usa abs)" {
    try std.testing.expectEqual(@as(u7, 2), bitCountSigned(-3));
    try std.testing.expectEqual(@as(u7, 2), bitCountSigned(3));
    try std.testing.expectEqual(@as(u7, 1), bitCountSigned(-1));
    try std.testing.expectEqual(@as(u7, 0), bitCountSigned(0));
}

test "tipos estrechos: el resultado depende del ancho" {
    const b: u8 = 0b1010_1010;
    try std.testing.expectEqual(@as(u4, 4), @popCount(b));
    try std.testing.expectEqual(@as(u4, 0), @clz(b));
    const z: u16 = 0;
    try std.testing.expectEqual(@as(u5, 16), @clz(z));
}''',
    apis_used=["@popCount","@clz","@bitCast","@intCast","std.math.maxInt"],
    constraints=["sin root","tipo sin signo para el patron de bits","bit_length depende del ancho (u64 -> 64 - @clz)"],
    preconditions=["x != 0 para el atajo de @clz (aqui se trata 0 aparte)"],
    postconditions=["bitLength(0) == 0","bitCount cuenta bits a 1 del patron"],
    side_effects=[],
    error_behavior="no fallan para enteros. std.math.log2_int(0) si hace panic (assert x != 0): no usarlo para bit_length sin comprobar 0.",
    ownership_memory="sin asignacion.",
    differences=["Python no tiene ancho: bit_length es sobre abs(x); en Zig el ancho lo fija el tipo y bit_length de u64 es 64 - @clz(x). Usar u64/i64 y documentar el limite","bit_count de Python usa abs(x) tambien para negativos; @popCount opera sobre el patron (complemento a dos), asi que hay que pasar abs(x) o bitcast","@clz(0) esta definido en Zig (devuelve el ancho), pero std.math.log2_int(0) hace panic","@popCount devuelve un entero sin signo del minimo ancho que cabe (u7 para u64); si se necesita usize, convertir con @intCast"],
    error_signatures=["error: expected integer or vector, found 'f64'"],
    provenance=PROV,
),
# ---------------------------------------------------------------- round
dict(
    operation_id="zig0.16/round-floor-ceil-bankers",
    name="redondeo: round, floor y ceil (y el empate al par)",
    intent="Redondear un float al entero mas cercano, hacia abajo o hacia arriba, y reproducir el redondeo de Python al par (banker's) cuando el valor cae justo en .5.",
    aliases=["round","math.floor","math.ceil","redondear al entero mas cercano","redondeo bancario","banker's rounding","redondear al par","@round","@floor","@ceil","redondear hacia abajo","redondear hacia arriba","round half to even","round(2.5)"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''import math
round(2.5)          # 2  (empate -> par)
round(3.5)          # 4
round(-2.5)         # -2
round(2.4)          # 2
round(2.675, 2)     # 2.67 (por la representacion binaria)
math.floor(-2.5)    # -3
math.ceil(-2.5)     # -2
math.floor(2.9)     # 2
math.ceil(2.1)      # 3''',
    zig_impl=r'''pub fn zigRound(x: f64) f64 { return @round(x); } // empate ALEJA de cero
pub fn zigFloor(x: f64) f64 { return @floor(x); }
pub fn zigCeil(x: f64) f64 { return @ceil(x); }

/// Equivalente a round(x) de Python: empate al par (banker's rounding).
pub fn roundHalfEven(x: f64) f64 {
    const f = @floor(x);
    const diff = x - f;
    if (diff < 0.5) return f;
    if (diff > 0.5) return f + 1.0;
    return if (@mod(f, 2.0) == 0.0) f else f + 1.0;
}''',
    zig_test=r'''const std = @import("std");

pub fn zigRound(x: f64) f64 {
    return @round(x);
}
pub fn zigFloor(x: f64) f64 {
    return @floor(x);
}
pub fn zigCeil(x: f64) f64 {
    return @ceil(x);
}

pub fn roundHalfEven(x: f64) f64 {
    const f = @floor(x);
    const diff = x - f;
    if (diff < 0.5) return f;
    if (diff > 0.5) return f + 1.0;
    // diff == 0.5 exacto: escoger el vecino par
    return if (@mod(f, 2.0) == 0.0) f else f + 1.0;
}

test "round de Python es a par; @round aleja de cero" {
    try std.testing.expectEqual(@as(f64, 3.0), zigRound(2.5));
    try std.testing.expectEqual(@as(f64, -3.0), zigRound(-2.5));
    try std.testing.expectEqual(@as(f64, 2.0), roundHalfEven(2.5));
    try std.testing.expectEqual(@as(f64, 4.0), roundHalfEven(3.5));
    try std.testing.expectEqual(@as(f64, -2.0), roundHalfEven(-2.5));
    try std.testing.expectEqual(@as(f64, -4.0), roundHalfEven(-3.5));
}

test "casos sin empate coinciden" {
    try std.testing.expectEqual(zigRound(2.4), roundHalfEven(2.4));
    try std.testing.expectEqual(zigRound(2.6), roundHalfEven(2.6));
    try std.testing.expectEqual(zigRound(-2.4), roundHalfEven(-2.4));
    try std.testing.expectEqual(@as(f64, 3.0), roundHalfEven(2.6));
}

test "floor y ceil" {
    try std.testing.expectEqual(@as(f64, -3.0), zigFloor(-2.5));
    try std.testing.expectEqual(@as(f64, -2.0), zigCeil(-2.5));
    try std.testing.expectEqual(@as(f64, 2.0), zigFloor(2.9));
    try std.testing.expectEqual(@as(f64, 3.0), zigCeil(2.1));
}

test "a entero con @intFromFloat (puede hacer panic si no cabe)" {
    try std.testing.expectEqual(@as(i32, -3), @as(i32, @intFromFloat(zigRound(-2.5))));
    try std.testing.expectEqual(@as(i32, 2), @as(i32, @intFromFloat(roundHalfEven(2.5))));
    try std.testing.expectEqual(@as(i32, 4), @as(i32, @intFromFloat(roundHalfEven(3.5))));
}''',
    apis_used=["@round","@floor","@ceil","@intFromFloat","@mod"],
    constraints=["sin root","@round/@floor/@ceil solo aceptan float (o vector de floats)","@intFromFloat puede hacer panic fuera de rango"],
    preconditions=["x finito para convertirlo a entero"],
    postconditions=["roundHalfEven devuelve un f64 entero","@floor <= x <= @ceil"],
    side_effects=[],
    error_behavior="@round/@floor/@ceil no fallan con floats (inf/nan se propagan); @intFromFloat hace panic si el valor no cabe o es nan/inf. Python round() de un float devuelve int sin error.",
    ownership_memory="sin asignacion; valores.",
    differences=["@round redondea el empate ALEJANDO de cero (2.5 -> 3, -2.5 -> -3); round() de Python redondea al par (2.5 -> 2, -2.5 -> -2). La variante roundHalfEven de arriba reproduce Python para empates exactos","@floor/@ceil devuelven float; math.floor/math.ceil de Python devuelven int (hay que convertir con @intFromFloat)","@round sobre un entero no compila (Python round(int) devuelve int): para enteros no hay nada que redondear","round(x, n) (n decimales) no tiene equivalente directo: usar formateo {d:.n} (ver parse-float-format-decimals), que tambien redondea distinto","el empate solo se detecta cuando x es exactamente representable como k+0.5; para el resto, diff nunca es exactamente 0.5"],
    error_signatures=["error: expected vector of floats or float type, found 'i32'",
                      "error: @intFromFloat must have a known result type"],
    provenance=PROV,
),
# ---------------------------------------------------------------- C strings
dict(
    operation_id="zig0.16/cstring-span-slice-to",
    name="c string con terminador NUL: span y sliceTo",
    intent="Convertir un puntero char* terminado en NUL en un slice de bytes, o cortar un buffer en el primer byte cero, sin copiar y sin perder el resto.",
    aliases=["c string","char*","puntero con terminador nulo","puntero terminado en NUL","std.mem.span","std.mem.sliceTo","bytes hasta el NUL","quitar el byte nulo final","ctypes.c_char_p","null terminated","sentinel","[:0]u8","puntero a array centinela","buffer con ceros"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''b"hola\x00mundo"                          # bytes con NUL dentro: son datos
b"hola\x00mundo".split(b"\x00")[0]       # b'hola'
b"abc\x00".rstrip(b"\x00")               # b'abc'
import ctypes
ctypes.c_char_p(b"hola").value           # b'hola' (hasta el NUL)
"hola".encode() + b"\x00"                # b'hola\x00' (forma C)
b"sin nulo".find(b"\x00")                # -1: no hay terminador''',
    zig_impl=r'''/// [*:0]const u8 (char* de C) -> slice sin copiar, longitud hasta el NUL.
pub fn fromCString(p: [*:0]const u8) []const u8 {
    return std.mem.span(p);
}

/// Buffer con longitud conocida y posible NUL dentro -> slice hasta el primer 0.
pub fn uptoNul(buf: []const u8) []const u8 {
    return std.mem.sliceTo(buf, 0);
}

/// Array [N:0]u8 -> slice sin el terminador.
pub fn fromSentinelArray(arr: *const [3:0]u8) []const u8 {
    return std.mem.sliceTo(arr, 0);
}
// OJO: std.mem.span NO acepta &array (puntero a array): usar sliceTo o [*:0].''',
    zig_test=r'''const std = @import("std");

pub fn fromCString(p: [*:0]const u8) []const u8 {
    return std.mem.span(p);
}

pub fn uptoNul(buf: []const u8) []const u8 {
    return std.mem.sliceTo(buf, 0);
}

pub fn fromSentinelArray(arr: *const [3:0]u8) []const u8 {
    return std.mem.sliceTo(arr, 0);
}

pub fn bytesLen(buf: []const u8) usize {
    return std.mem.sliceTo(buf, 0).len;
}

test "span de un puntero C" {
    const p: [*:0]const u8 = "hola";
    const s = fromCString(p);
    try std.testing.expectEqualStrings("hola", s);
    try std.testing.expectEqual(@as(usize, 4), s.len);
    try std.testing.expectEqual(@as(usize, 0), fromCString("").len);
}

test "span de un array centinela con cast a [*:0]" {
    const buf = [_:0]u8{ 'a', 'b', 'c' };
    const p: [*:0]const u8 = &buf;
    try std.testing.expectEqualStrings("abc", fromCString(p));
}

test "sliceTo corta en el primer NUL" {
    const raw = [_]u8{ 'h', 'o', 'l', 'a', 0, 'x', 'y' };
    try std.testing.expectEqualStrings("hola", uptoNul(&raw));
    try std.testing.expectEqual(@as(usize, 4), bytesLen(&raw));
    const sin = [_]u8{ 'a', 'b', 'c' };
    try std.testing.expectEqualStrings("abc", uptoNul(&sin));
    try std.testing.expectEqualStrings("", uptoNul(&[_]u8{ 0, 'z' }));
}

test "sliceTo sin NUL devuelve todo (como find == -1)" {
    const s = "sin terminador";
    try std.testing.expectEqualStrings(s, std.mem.sliceTo(s, 0));
}

test "array con centinela: sliceTo le quita el NUL" {
    const buf = [_:0]u8{ 'a', 'b', 'c' };
    try std.testing.expectEqual(@as(u8, 0), buf[3]);
    try std.testing.expectEqualStrings("abc", fromSentinelArray(&buf));
}

test "span de puntero [*c]" {
    const p: [*c]const u8 = "hola";
    try std.testing.expectEqualStrings("hola", std.mem.span(p));
}''',
    apis_used=["std.mem.span","std.mem.sliceTo","[*:0]const u8","[*c]const u8","[N:0]u8"],
    constraints=["sin root","el puntero debe apuntar a memoria con terminador 0 valido","no copia: el slice aliasea el original"],
    preconditions=["para span: puntero many-item con centinela 0 (o [*c])","para sliceTo: puntero a array, many-item o slice"],
    postconditions=["span devuelve []const u8 hasta el primer 0 (sin incluirlo)","sliceTo sin el terminador devuelve todo el buffer"],
    side_effects=[],
    error_behavior="span recorre memoria hasta el NUL: un buffer sin terminador es UB (lectura fuera de rango), igual que strlen. sliceTo esta acotado por la longitud conocida: no se sale.",
    ownership_memory="span/sliceTo no asignan: devuelven un slice que apunta al buffer original; no liberar.",
    differences=["std.mem.span exige un puntero con centinela ([*:0], [*c]); un literal o &array ([*]const [N:0]u8, puntero a array) no compila: para arrays usar std.mem.sliceTo(&arr, 0) o indexar arr[0..N]","bytes de Python son datos con longitud: un NUL dentro no termina nada; en Zig solo los punteros C tienen terminador","sliceTo(buf, 0) equivale a split(b'\\x00')[0] pero sin asignar y sin copiar","ctypes.c_char_p con None se modela como ?[*:0]const u8 y span devuelve un opcional","no hay conversion de codificacion: son bytes, como bytes de Python"],
    error_signatures=["error: invalid type given to std.mem.span: *const [4:0]u8"],
    provenance=PROV,
),
]

_SKIP = dict(skip_reason="sin driver diferencial todavia")

CONTRACTS = {
    "zig0.16/format-string-alloc-print": _c(None, None, None, [],
        type_sig={"input": "valores", "output": "bytes"}, **_SKIP),
    "zig0.16/float-special-values-isinf-isnan": _c(None, None, None, [],
        type_sig={"input": "f64", "output": "bool"}, **_SKIP),
    "zig0.16/struct-pack-endian-readint": _c(None, None, None, [],
        type_sig={"input": "entero/bytes", "output": "bytes/entero o error"}, **_SKIP),
    "zig0.16/int-from-bytes-to-bytes-endian": _c(None, None, None, [],
        type_sig={"input": "entero/bytes", "output": "bytes/entero"}, **_SKIP),
    "zig0.16/div-floor-mod-negative": _c(None, None, None, [],
        type_sig={"input": "par de enteros", "output": "entero"}, **_SKIP),
    "zig0.16/int-bit-count-bit-length": _c(None, None, None, [],
        type_sig={"input": "entero", "output": "entero"}, **_SKIP),
    "zig0.16/round-floor-ceil-bankers": _c(None, None, None, [],
        type_sig={"input": "f64", "output": "f64"}, **_SKIP),
    "zig0.16/cstring-span-slice-to": _c(None, None, None, [],
        type_sig={"input": "puntero/bytes", "output": "bytes"}, **_SKIP),
}
