"""Recetas texto y numeros (area texto_num). Generado y verificado con zig test."""
from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"; PY = "3.12"; PROV = "std local de zig 0.16.0 (repo en lib/std)"

ENTRIES = [
dict(
    operation_id="zig0.16/base64-encode-decode",
    name="codificar y decodificar base64",
    intent="Convertir bytes a texto base64 estandar y volver, rechazando entrada invalida con un error en vez de ignorarla.",
    aliases=["base64.b64encode","base64.b64decode","binascii.Error","base64 encode","base64 decode","codificar en base64","decodificar base64","bytes a texto base64","b64 string to bytes","base64 invalido","Incorrect padding","std.base64"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''import base64
base64.b64encode(b"hello world")         # b'aGVsbG8gd29ybGQ='
base64.b64decode("aGVsbG8gd29ybGQ=")     # b'hello world'
base64.b64decode("aGVsbG8")              # binascii.Error: Incorrect padding
base64.b64decode("aGVs\nbG8=")           # b'hello': por defecto DESCARTA caracteres fuera del alfabeto
base64.b64decode("aGVs!bG8=", validate=True)  # binascii.Error''',
    zig_impl=r'''pub fn b64Encode(allocator: std.mem.Allocator, data: []const u8) ![]u8 {
    const enc = std.base64.standard.Encoder;
    const out = try allocator.alloc(u8, enc.calcSize(data.len));
    errdefer allocator.free(out);
    _ = enc.encode(out, data);
    return out;
}

pub fn b64Decode(allocator: std.mem.Allocator, text: []const u8) ![]u8 {
    const dec = std.base64.standard.Decoder;
    const size = try dec.calcSizeForSlice(text);
    const out = try allocator.alloc(u8, size);
    errdefer allocator.free(out);
    try dec.decode(out, text);
    return out;
}''',
    zig_test=r'''const std = @import("std");

pub fn b64Encode(allocator: std.mem.Allocator, data: []const u8) ![]u8 {
    const enc = std.base64.standard.Encoder;
    const out = try allocator.alloc(u8, enc.calcSize(data.len));
    errdefer allocator.free(out);
    _ = enc.encode(out, data);
    return out;
}

pub fn b64Decode(allocator: std.mem.Allocator, text: []const u8) ![]u8 {
    const dec = std.base64.standard.Decoder;
    const size = try dec.calcSizeForSlice(text);
    const out = try allocator.alloc(u8, size);
    errdefer allocator.free(out);
    try dec.decode(out, text);
    return out;
}

test "encode coincide con base64.b64encode" {
    const a = std.testing.allocator;
    const s = try b64Encode(a, "hello world");
    defer a.free(s);
    try std.testing.expectEqualStrings("aGVsbG8gd29ybGQ=", s);
    const e = try b64Encode(a, "");
    defer a.free(e);
    try std.testing.expectEqualStrings("", e);
}

test "roundtrip con bytes binarios" {
    const a = std.testing.allocator;
    const raw = [_]u8{ 0x00, 0xff, 0xfe, 0x10, 0x80 };
    const s = try b64Encode(a, &raw);
    defer a.free(s);
    const back = try b64Decode(a, s);
    defer a.free(back);
    try std.testing.expectEqualSlices(u8, &raw, back);
}

test "entrada invalida da error como binascii.Error" {
    const a = std.testing.allocator;
    try std.testing.expectError(error.InvalidPadding, b64Decode(a, "aGVsbG8"));
    try std.testing.expectError(error.InvalidCharacter, b64Decode(a, "aGVs!G8="));
    // el decoder estricto no ignora saltos de linea
    try std.testing.expectError(error.InvalidCharacter, b64Decode(a, "aGV\nbG8="));
}''',
    apis_used=["std.base64.standard.Encoder.calcSize","std.base64.standard.Encoder.encode","std.base64.standard.Decoder.calcSizeForSlice","std.base64.standard.Decoder.decode"],
    constraints=["sin root","gpa"],
    preconditions=["alfabeto estandar con relleno '='"],
    postconditions=["encode devuelve texto ASCII de longitud 4*ceil(n/3)","decode devuelve los bytes originales"],
    side_effects=[],
    error_behavior="decode: error.InvalidPadding (longitud/relleno), error.InvalidCharacter (fuera del alfabeto); alloc: OutOfMemory.",
    ownership_memory="el llamador libera el slice devuelto; encode/decode escriben en un buffer exacto precalculado con calcSize*.",
    differences=["Python b64decode por defecto DESCARTA caracteres no alfabeticos (saltos de linea incluidos); el Decoder estandar de Zig es estricto, como validate=True: devuelve InvalidCharacter","los errores son error.InvalidPadding / error.InvalidCharacter, no binascii.Error","para variante URL usar std.base64.url_safe / url_safe_no_pad (urlsafe_b64encode); para ignorar espacios existe Base64DecoderWithIgnore","Decoder.decode exige dest.len exacto (usar calcSizeForSlice); un tamano distinto no es el contrato"],
    provenance=PROV,
),
dict(
    operation_id="zig0.16/hex-encode-decode",
    name="bytes a hex y hex a bytes",
    intent="Convertir un buffer a su representacion hexadecimal en minusculas y parsear hex de vuelta con errores en entrada invalida.",
    aliases=["bytes.hex()","bytes.fromhex","binascii.hexlify","binascii.unhexlify","bytes a cadena hexadecimal","cadena hexadecimal a bytes","hex string to bytes","bytes to hex string","parsear hex","std.fmt.hexToBytes","std.fmt.bytesToHex", "convertir bytes a hexadecimal", "buffer a hex"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''b"\xde\xad\xbe\xef".hex()        # 'deadbeef'
bytes.fromhex("DeAdBeEf")           # b'\xde\xad\xbe\xef'
bytes.fromhex("abc")                # ValueError (longitud impar)
bytes.fromhex("de ad")              # b'\xde\xad'  (Python IGNORA espacios entre bytes)''',
    zig_impl=r'''pub fn toHex(allocator: std.mem.Allocator, data: []const u8) ![]u8 {
    const out = try allocator.alloc(u8, data.len * 2);
    errdefer allocator.free(out);
    const charset = "0123456789abcdef";
    for (data, 0..) |b, i| {
        out[i * 2] = charset[b >> 4];
        out[i * 2 + 1] = charset[b & 0x0f];
    }
    return out;
}

pub fn fromHex(allocator: std.mem.Allocator, text: []const u8) ![]u8 {
    if (text.len % 2 != 0) return error.InvalidLength;
    const out = try allocator.alloc(u8, text.len / 2);
    errdefer allocator.free(out);
    _ = try std.fmt.hexToBytes(out, text);
    return out;
}''',
    zig_test=r'''const std = @import("std");

pub fn toHex(allocator: std.mem.Allocator, data: []const u8) ![]u8 {
    const out = try allocator.alloc(u8, data.len * 2);
    errdefer allocator.free(out);
    const charset = "0123456789abcdef";
    for (data, 0..) |b, i| {
        out[i * 2] = charset[b >> 4];
        out[i * 2 + 1] = charset[b & 0x0f];
    }
    return out;
}

pub fn fromHex(allocator: std.mem.Allocator, text: []const u8) ![]u8 {
    if (text.len % 2 != 0) return error.InvalidLength;
    const out = try allocator.alloc(u8, text.len / 2);
    errdefer allocator.free(out);
    _ = try std.fmt.hexToBytes(out, text);
    return out;
}

test "bytes.hex() equivalente" {
    const a = std.testing.allocator;
    const s = try toHex(a, &[_]u8{ 0xde, 0xad, 0xbe, 0xef, 0x00 });
    defer a.free(s);
    try std.testing.expectEqualStrings("deadbeef00", s);
}

test "fromhex acepta mayusculas y minusculas" {
    const a = std.testing.allocator;
    const b = try fromHex(a, "DeAdBeEf");
    defer a.free(b);
    try std.testing.expectEqualSlices(u8, &[_]u8{ 0xde, 0xad, 0xbe, 0xef }, b);
    const e = try fromHex(a, "");
    defer a.free(e);
    try std.testing.expectEqual(@as(usize, 0), e.len);
}

test "longitud impar o caracter no hex dan error" {
    const a = std.testing.allocator;
    try std.testing.expectError(error.InvalidLength, fromHex(a, "abc"));
    try std.testing.expectError(error.InvalidCharacter, fromHex(a, "zz"));
    // Python fromhex ignora espacios entre bytes; aqui es error
    try std.testing.expectError(error.InvalidCharacter, fromHex(a, "de ad "));
}''',
    apis_used=["std.fmt.hexToBytes","std.mem.Allocator.alloc"],
    constraints=["sin root","gpa"],
    preconditions=["texto hex con pares de digitos"],
    postconditions=["toHex devuelve 2*n bytes en minusculas","fromHex devuelve n/2 bytes"],
    side_effects=[],
    error_behavior="fromHex: error.InvalidLength (longitud impar), error.InvalidCharacter (no hex); alloc: OutOfMemory.",
    ownership_memory="el llamador libera ambos slices; con longitud comptime-known std.fmt.bytesToHex(arr, .lower) devuelve un array sin asignar.",
    differences=["bytes.fromhex ignora espacios ASCII entre pares; hexToBytes los rechaza (InvalidCharacter)","los errores son error.InvalidLength / error.InvalidCharacter, no ValueError","bytes.hex(sep) admite separador; aqui hay que montarlo a mano","fromhex acepta mayusculas y minusculas, igual que hexToBytes; bytesToHex/toHex solo emiten el caso elegido"],
    provenance=PROV,
),
dict(
    operation_id="zig0.16/parse-int-base-overflow",
    name="parsear enteros con base y formatearlos",
    intent="Convertir texto a entero con base 2-36 distinguiendo desbordamiento de caracter invalido, y escribir un entero como texto en un buffer.",
    aliases=["int(s, base)","int(s)","str(n)","format(n, 'x')","parsear entero","string a entero","entero a string","OverflowError","ValueError invalid literal for int","std.fmt.parseInt","bufPrint entero","convertir hex a int"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''int("42"); int("-42"); int("ff", 16); int("101", 2)
int("0xff", 0)            # 255 (base 0 detecta prefijo)
int(" 7 ")                # 7  (Python recorta espacios)
int("1_0")                # 10 (guion bajo entre digitos)
int("12a")                # ValueError
int("2147483648")         # sin limite: Python usa enteros arbitrarios
str(-123456); format(255, "x")  # '-123456', 'ff' ''',
    zig_impl=r'''pub fn parseI32(text: []const u8, base: u8) !i32 {
    return std.fmt.parseInt(i32, text, base);
}

pub fn intToStr(buf: []u8, n: i64) ![]u8 {
    return std.fmt.bufPrint(buf, "{d}", .{n});
}

pub fn intToStrBase(buf: []u8, n: u32, base: u8) []u8 {
    // equivalente a format(n, 'x') / format(n, 'b'): solo bases 2..36 minusculas
    return buf[0..std.fmt.printInt(buf, n, base, .lower, .{})];
}''',
    zig_test=r'''const std = @import("std");

pub fn parseI32(text: []const u8, base: u8) !i32 {
    return std.fmt.parseInt(i32, text, base);
}

pub fn intToStr(buf: []u8, n: i64) ![]u8 {
    return std.fmt.bufPrint(buf, "{d}", .{n});
}

pub fn intToStrBase(buf: []u8, n: u32, base: u8) []u8 {
    // equivalente a format(n, 'x') / format(n, 'b'): solo bases 2..36 minusculas
    return buf[0..std.fmt.printInt(buf, n, base, .lower, .{})];
}

test "int(s) en base 10 y 16" {
    try std.testing.expectEqual(@as(i32, 42), try parseI32("42", 10));
    try std.testing.expectEqual(@as(i32, -42), try parseI32("-42", 10));
    try std.testing.expectEqual(@as(i32, 255), try parseI32("ff", 16));
    try std.testing.expectEqual(@as(i32, 255), try parseI32("FF", 16));
    try std.testing.expectEqual(@as(i32, 5), try parseI32("101", 2));
    try std.testing.expectEqual(@as(i32, 255), try parseI32("0xff", 0));
}

test "overflow e invalido son errores distintos" {
    try std.testing.expectError(error.Overflow, parseI32("2147483648", 10));
    try std.testing.expectEqual(@as(i32, std.math.minInt(i32)), try parseI32("-2147483648", 10));
    try std.testing.expectError(error.InvalidCharacter, parseI32("12a", 10));
    try std.testing.expectError(error.InvalidCharacter, parseI32("", 10));
    try std.testing.expectError(error.InvalidCharacter, parseI32(" 7", 10));
    try std.testing.expectError(error.InvalidCharacter, parseI32("7\n", 10));
}

test "str(n) con bufPrint y NoSpaceLeft" {
    var buf: [8]u8 = undefined;
    try std.testing.expectEqualStrings("-123456", try intToStr(&buf, -123456));
    try std.testing.expectError(error.NoSpaceLeft, intToStr(&buf, 1234567890123));
}

test "formato en otra base" {
    var buf: [40]u8 = undefined;
    try std.testing.expectEqualStrings("ff", intToStrBase(&buf, 255, 16));
    try std.testing.expectEqualStrings("101", intToStrBase(&buf, 5, 2));
}''',
    apis_used=["std.fmt.parseInt","std.fmt.bufPrint","std.fmt.printInt","error.Overflow","error.InvalidCharacter"],
    constraints=["sin root","tipo destino fijo (i32)"],
    preconditions=["texto sin espacios"],
    postconditions=["parseI32 devuelve un i32 exacto o un error","intToStr devuelve un slice del buffer"],
    side_effects=[],
    error_behavior="parseInt: error.InvalidCharacter (vacio o caracter invalido) y error.Overflow (no cabe en T); bufPrint: error.NoSpaceLeft.",
    ownership_memory="sin asignacion; buffer de pila del llamador.",
    differences=["Python no desborda (enteros ilimitados): el tipo destino de Zig impone el rango y da error.Overflow","int() recorta espacios y saltos de linea; parseInt los rechaza (InvalidCharacter): hay que std.mem.trim antes","parseInt acepta '_' entre digitos como Python (sin '_' al inicio o al final) pero Python tambien acepta digitos Unicode (int('٣') == 3) y Zig no","con base 0 parseInt detecta 0b/0o/0x como Python; Python ademas admite 0 a secas y prohibe ceros a la izquierda en base 0","parseInt en tipo sin signo acepta '-0' (da 0) y da Overflow con '-1'"],
    provenance=PROV,
),
dict(
    operation_id="zig0.16/parse-float-format-decimals",
    name="parsear float y formatear con decimales fijos",
    intent="Convertir texto a f64 con error si es invalido y escribir un float con un numero fijo de decimales.",
    aliases=["float(s)","f'{x:.2f}'","'%.2f' % x","round(x, 2)","string a float","parsear numero decimal","formatear con dos decimales","std.fmt.parseFloat","float invalido ValueError","float to string precision","decimal places"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''float("3.14"); float("-1.5e3"); float("inf")
float("1,5")                      # ValueError
float(" 1.5 ")                    # 1.5 (recorta espacios)
f"{2.675:.2f}"                    # '2.67' (valor binario exacto 2.67499999...)
f"{0.125:.2f}"                    # '0.12' (empate -> par)
"%.0f" % 2.5                      # '2' ''',
    zig_impl=r'''pub fn parseF64(text: []const u8) !f64 {
    return std.fmt.parseFloat(f64, text);
}

pub fn fixed2(buf: []u8, x: f64) ![]u8 {
    return std.fmt.bufPrint(buf, "{d:.2}", .{x});
}''',
    zig_test=r'''const std = @import("std");

pub fn parseF64(text: []const u8) !f64 {
    return std.fmt.parseFloat(f64, text);
}

pub fn fixed2(buf: []u8, x: f64) ![]u8 {
    return std.fmt.bufPrint(buf, "{d:.2}", .{x});
}

test "float(s) basico" {
    try std.testing.expectEqual(@as(f64, 3.14), try parseF64("3.14"));
    try std.testing.expectEqual(@as(f64, -1500.0), try parseF64("-1.5e3"));
    try std.testing.expectEqual(@as(f64, 2.0), try parseF64("+2"));
    try std.testing.expect(std.math.isInf(try parseF64("inf")));
    try std.testing.expect(std.math.isNan(try parseF64("nan")));
}

test "float invalido da InvalidCharacter" {
    try std.testing.expectError(error.InvalidCharacter, parseF64(""));
    try std.testing.expectError(error.InvalidCharacter, parseF64("1,5"));
    try std.testing.expectError(error.InvalidCharacter, parseF64("abc"));
    try std.testing.expectError(error.InvalidCharacter, parseF64("1.5x"));
}

test "formato con 2 decimales" {
    var buf: [32]u8 = undefined;
    try std.testing.expectEqualStrings("3.14", try fixed2(&buf, 3.14159));
    try std.testing.expectEqualStrings("2.00", try fixed2(&buf, 2));
    try std.testing.expectEqualStrings("-0.50", try fixed2(&buf, -0.5));
    try std.testing.expectEqualStrings("1234.57", try fixed2(&buf, 1234.567));
}''',
    apis_used=["std.fmt.parseFloat","std.fmt.bufPrint","{d:.N}"],
    constraints=["sin root","tipo f64"],
    preconditions=["texto sin espacios"],
    postconditions=["parseF64 devuelve f64 o error","fixed2 devuelve un slice del buffer con exactamente 2 decimales"],
    side_effects=[],
    error_behavior="parseFloat: error.InvalidCharacter; bufPrint: error.NoSpaceLeft.",
    ownership_memory="sin asignacion; buffer de pila del llamador.",
    differences=["el redondeo de {d:.2} NO es el de Python: Zig 2.675 -> '2.68', 0.125 -> '0.13', 2.5 con .0 -> '3' (mitad hacia arriba sobre la representacion decimal mas corta); Python da '2.67', '0.12', '2'","parseFloat no recorta espacios (InvalidCharacter), acepta '_' entre digitos, 'inf'/'infinity'/'nan', '.5', '5.' y hexfloat 0x1p3","si hace falta paridad exacta de redondeo con Python hay que implementarla aparte (no demostrada aqui)","un solo error (InvalidCharacter) cubre todo; no hay distincion como en Python"],
    provenance=PROV,
),
dict(
    operation_id="zig0.16/str-find-replace-affix",
    name="buscar, reemplazar y comprobar prefijo/sufijo",
    intent="Equivalentes de str.startswith, str.endswith, str.find y str.replace sobre bytes UTF-8 con asignacion explicita.",
    aliases=["str.startswith","str.endswith","str.find","str.replace","str.index","str.count","buscar subcadena","reemplazar texto","comprobar prefijo","comprobar sufijo","substring search","std.mem.find","std.mem.replaceOwned"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''"foo.txt".startswith("foo"); "foo.txt".endswith(".txt")
"foo.bar".find("bar")        # 4
"foo".find("z")              # -1
"é-e".find("e")              # 2 (indice en codepoints)
"aaa".replace("aa", "b")     # 'ba'
"abc".replace("", "-")       # '-a-b-c-' (needle vacio permitido)''',
    zig_impl=r'''pub fn startsWith(s: []const u8, prefix: []const u8) bool {
    return std.mem.startsWith(u8, s, prefix);
}

pub fn endsWith(s: []const u8, suffix: []const u8) bool {
    return std.mem.endsWith(u8, s, suffix);
}

/// str.find: indice en BYTES o null (Python devuelve -1 e indices en codepoints).
pub fn find(s: []const u8, needle: []const u8) ?usize {
    return std.mem.find(u8, s, needle);
}

/// str.replace(old, new) sin limite. `old` vacio es error (Python intercala `new`).
pub fn replaceAll(allocator: std.mem.Allocator, s: []const u8, old: []const u8, new: []const u8) ![]u8 {
    if (old.len == 0) return error.EmptyNeedle;
    return std.mem.replaceOwned(u8, allocator, s, old, new);
}''',
    zig_test=r'''const std = @import("std");

pub fn startsWith(s: []const u8, prefix: []const u8) bool {
    return std.mem.startsWith(u8, s, prefix);
}

pub fn endsWith(s: []const u8, suffix: []const u8) bool {
    return std.mem.endsWith(u8, s, suffix);
}

/// str.find: indice en BYTES o null (Python devuelve -1 e indices en codepoints).
pub fn find(s: []const u8, needle: []const u8) ?usize {
    return std.mem.find(u8, s, needle);
}

/// str.replace(old, new) sin limite. `old` vacio es error (Python intercala `new`).
pub fn replaceAll(allocator: std.mem.Allocator, s: []const u8, old: []const u8, new: []const u8) ![]u8 {
    if (old.len == 0) return error.EmptyNeedle;
    return std.mem.replaceOwned(u8, allocator, s, old, new);
}

test "startswith / endswith" {
    try std.testing.expect(startsWith("foo.txt", "foo"));
    try std.testing.expect(!startsWith("fo", "foo"));
    try std.testing.expect(startsWith("abc", ""));
    try std.testing.expect(endsWith("foo.txt", ".txt"));
    try std.testing.expect(!endsWith("txt", "x.txt"));
}

test "find devuelve indice de byte u optional" {
    try std.testing.expectEqual(@as(?usize, 4), find("foo.bar", "bar"));
    try std.testing.expectEqual(@as(?usize, null), find("foo", "z"));
    try std.testing.expectEqual(@as(?usize, 0), find("abc", ""));
    // indice en bytes: 'e' va tras 'é' (2 bytes), Python daria 2
    try std.testing.expectEqual(@as(?usize, 3), find("é-e", "e"));
}

test "replace all con asignacion" {
    const a = std.testing.allocator;
    const r = try replaceAll(a, "a-b-c", "-", "::");
    defer a.free(r);
    try std.testing.expectEqualStrings("a::b::c", r);
    const none = try replaceAll(a, "abc", "z", "y");
    defer a.free(none);
    try std.testing.expectEqualStrings("abc", none);
    const del = try replaceAll(a, "a-b-c", "-", "");
    defer a.free(del);
    try std.testing.expectEqualStrings("abc", del);
    // sin solapamiento, de izquierda a derecha, igual que Python
    const ov = try replaceAll(a, "aaa", "aa", "b");
    defer a.free(ov);
    try std.testing.expectEqualStrings("ba", ov);
}

test "needle vacio es error en vez de panic" {
    try std.testing.expectError(error.EmptyNeedle, replaceAll(std.testing.allocator, "abc", "", "-"));
}''',
    apis_used=["std.mem.startsWith","std.mem.endsWith","std.mem.find","std.mem.replaceOwned"],
    constraints=["sin root","gpa para replace"],
    preconditions=["texto como bytes"],
    postconditions=["find devuelve indice de byte u null","replaceAll devuelve una copia nueva"],
    side_effects=[],
    error_behavior="replaceAll: error.EmptyNeedle (guarda propia) y OutOfMemory; sin la guarda, std.mem.replace con needle vacio es un assert/UB.",
    ownership_memory="el llamador libera el resultado de replaceAll; el resto no asigna.",
    differences=["find da indice en BYTES y null, Python da indice en codepoints y -1","needle vacio: Python lo admite en replace, std.mem.replaceOwned lo prohibe (assert needle.len > 0); la receta lo convierte en error","en 0.16 se llama std.mem.find/findLast/findPos (antes indexOf*)","replace con limite (count=N) no existe en std: hay que iterar con std.mem.find","la comparacion es byte a byte: no hay normalizacion Unicode (NFC/NFD)"],
    provenance=PROV,
),
dict(
    operation_id="zig0.16/utf8-codepoints-validate",
    name="iterar codepoints UTF-8 y validar texto",
    intent="Validar que unos bytes son UTF-8 correcto, contar codepoints e iterarlos, rechazando secuencias invalidas.",
    aliases=["bytes.decode('utf-8')","UnicodeDecodeError","len(str)","for ch in s","ord(ch)","iterar caracteres unicode","validar utf-8","contar codepoints","invalid utf8","utf-8 invalido","std.unicode.Utf8View","std.unicode.utf8ValidateSlice"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''s = "aé€".encode()
len(s)                       # 6 bytes
len(s.decode())              # 3 codepoints
[ord(c) for c in s.decode()] # [97, 233, 8364]
b"\xff".decode()             # UnicodeDecodeError
b"\xc0\x80".decode()         # error: sobrelargo
b"\xed\xa0\x80".decode()     # error: sustituto U+D800''',
    zig_impl=r'''pub fn isValidUtf8(bytes: []const u8) bool {
    return std.unicode.utf8ValidateSlice(bytes);
}

/// len(bytes.decode("utf-8")): error.InvalidUtf8 si no es valido.
pub fn countCodepoints(bytes: []const u8) !usize {
    const view = try std.unicode.Utf8View.init(bytes);
    var it = view.iterator();
    var n: usize = 0;
    while (it.nextCodepoint()) |_| n += 1;
    return n;
}

/// Suma de los codepoints (para demostrar la iteracion); tambien valida.
pub fn codepointSum(bytes: []const u8) !u64 {
    const view = try std.unicode.Utf8View.init(bytes);
    var it = view.iterator();
    var sum: u64 = 0;
    while (it.nextCodepoint()) |cp| sum += cp;
    return sum;
}''',
    zig_test=r'''const std = @import("std");

pub fn isValidUtf8(bytes: []const u8) bool {
    return std.unicode.utf8ValidateSlice(bytes);
}

/// len(bytes.decode("utf-8")): error.InvalidUtf8 si no es valido.
pub fn countCodepoints(bytes: []const u8) !usize {
    const view = try std.unicode.Utf8View.init(bytes);
    var it = view.iterator();
    var n: usize = 0;
    while (it.nextCodepoint()) |_| n += 1;
    return n;
}

/// Suma de los codepoints (para demostrar la iteracion); tambien valida.
pub fn codepointSum(bytes: []const u8) !u64 {
    const view = try std.unicode.Utf8View.init(bytes);
    var it = view.iterator();
    var sum: u64 = 0;
    while (it.nextCodepoint()) |cp| sum += cp;
    return sum;
}

test "iterar codepoints, no bytes" {
    try std.testing.expectEqual(@as(usize, 3), try countCodepoints("aé€"));
    try std.testing.expectEqual(@as(usize, 6), "aé€".len); // 1+2+3 bytes
    try std.testing.expectEqual(@as(usize, 1), try countCodepoints("😀"));
    try std.testing.expectEqual(@as(u64, 'a' + 0xe9 + 0x20ac), try codepointSum("aé€"));
    try std.testing.expectEqual(@as(usize, 0), try countCodepoints(""));
}

test "UTF-8 invalido se rechaza" {
    try std.testing.expect(!isValidUtf8("\xff"));
    try std.testing.expect(!isValidUtf8("\xc0\x80")); // sobrelargo
    try std.testing.expect(!isValidUtf8("\xed\xa0\x80")); // sustituto U+D800
    try std.testing.expect(!isValidUtf8("\xe2\x82")); // truncado
    try std.testing.expect(!isValidUtf8("\xf4\x90\x80\x80")); // > U+10FFFF
    try std.testing.expect(isValidUtf8("\xf4\x8f\xbf\xbf")); // U+10FFFF
    try std.testing.expectError(error.InvalidUtf8, countCodepoints("ok\xff"));
}''',
    apis_used=["std.unicode.utf8ValidateSlice","std.unicode.Utf8View.init","std.unicode.Utf8Iterator.nextCodepoint","std.unicode.utf8CountCodepoints"],
    constraints=["sin root","sin asignacion"],
    preconditions=["bytes cualesquiera"],
    postconditions=["countCodepoints devuelve el numero de codepoints (no de grafemas)","error.InvalidUtf8 si hay cualquier secuencia invalida"],
    side_effects=[],
    error_behavior="Utf8View.init devuelve error.InvalidUtf8; Utf8Iterator.nextCodepoint solo es seguro sobre un Utf8View ya validado (usa catch unreachable).",
    ownership_memory="sin asignacion; los slices apuntan al buffer original.",
    differences=["un 'caracter' de Python es un codepoint; ni Python ni esta receta cuentan grafemas (e + acento combinante = 2)","Python decode(errors='replace'/'ignore') tiene tolerancia; aqui validar es todo-o-nada, hay que recorrer a mano con utf8ByteSequenceLength/utf8Decode para ser tolerante","validacion equivalente a la de Python: rechaza sobrelargos, sustitutos y > U+10FFFF","la iteracion sin validar previamente (initUnchecked) con bytes invalidos es comportamiento indefinido por catch unreachable"],
    provenance=PROV,
),
dict(
    operation_id="zig0.16/ascii-case-lower-upper",
    name="minusculas y mayusculas solo ASCII",
    intent="Pasar texto a minusculas o mayusculas y comparar sin distinguir caso con la std, que solo conoce ASCII.",
    aliases=["str.lower","str.upper","lower()","upper()","convertir a minusculas","convertir a mayusculas","comparar sin distinguir mayusculas","case insensitive compare","std.ascii.lowerString","std.ascii.eqlIgnoreCase","ASCII vs Unicode", "comparar ignorando mayusculas"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''"Hello, WORLD".lower()       # 'hello, world'
"ÉCOLE".lower()              # 'école'  (Unicode)
"straße".upper()             # 'STRASSE' (cambia la longitud)
"İ".lower()                  # 'i̇' (2 codepoints)
"Content-Type".lower() == "content-type" ''',
    zig_impl=r'''/// str.lower() SOLO ASCII: los bytes >= 0x80 pasan intactos.
pub fn lowerAscii(allocator: std.mem.Allocator, s: []const u8) ![]u8 {
    return std.ascii.allocLowerString(allocator, s);
}

pub fn upperAscii(allocator: std.mem.Allocator, s: []const u8) ![]u8 {
    const out = try allocator.alloc(u8, s.len);
    return std.ascii.upperString(out, s);
}

/// a.lower() == b.lower() solo para ASCII.
pub fn eqlIgnoreCaseAscii(a: []const u8, b: []const u8) bool {
    return std.ascii.eqlIgnoreCase(a, b);
}''',
    zig_test=r'''const std = @import("std");

/// str.lower() SOLO ASCII: los bytes >= 0x80 pasan intactos.
pub fn lowerAscii(allocator: std.mem.Allocator, s: []const u8) ![]u8 {
    return std.ascii.allocLowerString(allocator, s);
}

pub fn upperAscii(allocator: std.mem.Allocator, s: []const u8) ![]u8 {
    const out = try allocator.alloc(u8, s.len);
    return std.ascii.upperString(out, s);
}

/// a.lower() == b.lower() solo para ASCII.
pub fn eqlIgnoreCaseAscii(a: []const u8, b: []const u8) bool {
    return std.ascii.eqlIgnoreCase(a, b);
}

test "lower/upper ASCII" {
    const a = std.testing.allocator;
    const lo = try lowerAscii(a, "Hello, WORLD 123");
    defer a.free(lo);
    try std.testing.expectEqualStrings("hello, world 123", lo);
    const up = try upperAscii(a, "Hello, world 123");
    defer a.free(up);
    try std.testing.expectEqualStrings("HELLO, WORLD 123", up);
}

test "no-ASCII queda intacto (Python lo cambiaria)" {
    const a = std.testing.allocator;
    const lo = try lowerAscii(a, "ÉCOLE");
    defer a.free(lo);
    // la E con acento (C3 89) no cambia; Python da "ecole" acentuado
    try std.testing.expectEqualStrings("\xc3\x89cole", lo);
    const up = try upperAscii(a, "straße");
    defer a.free(up);
    // Python: "STRASSE"; aqui 'ß' no se toca y queda en minuscula
    try std.testing.expectEqualStrings("STRA\xc3\x9fE", up);
}

test "comparar sin distinguir mayusculas" {
    try std.testing.expect(eqlIgnoreCaseAscii("Content-Type", "content-type"));
    try std.testing.expect(!eqlIgnoreCaseAscii("abc", "abcd"));
    try std.testing.expect(!eqlIgnoreCaseAscii("É", "é"));
}''',
    apis_used=["std.ascii.allocLowerString","std.ascii.upperString","std.ascii.eqlIgnoreCase","std.ascii.toLower","std.ascii.toUpper"],
    constraints=["sin root","gpa"],
    preconditions=["texto como bytes"],
    postconditions=["la copia tiene la misma longitud en bytes","bytes >= 0x80 intactos"],
    side_effects=[],
    error_behavior="no falla salvo OutOfMemory.",
    ownership_memory="el llamador libera el slice devuelto.",
    differences=["std 0.16 solo hace mapeo ASCII; no hay tablas de case Unicode en std.unicode (ver gap unicode-case-mapping)","'ÉCOLE' -> bytes 'É' intactos; Python da 'école'; 'straße'.upper() es 'STRASSE' en Python y deja 'ß' en Zig","apto para cabeceras HTTP, claves, comandos y tokens ASCII; no para texto de usuario internacional","casefold de Python no tiene equivalente"],
    provenance=PROV,
),
dict(
    operation_id="zig0.16/unicode-case-mapping",
    name="minusculas/mayusculas Unicode completas (NO DEMOSTRADO)",
    intent="Convertir a minusculas o mayusculas texto con letras no ASCII (acentos, ene, ss alemana, griego) o hacer casefold, como str.lower/str.upper/str.casefold de Python.",
    aliases=["str.lower unicode","str.upper unicode","str.casefold","mayusculas con acentos","minusculas con acentos","unicode case mapping","uppercase non-ascii","normalizar caso","comparar sin caso unicode", "mayusculas con eñes", "casefold unicode", "texto con tildes a mayusculas"],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''"ÉCOLE".lower()       # 'école'
"straße".upper()      # 'STRASSE'
"ǅ".upper()           # 'Ǆ'
"Σ".lower()           # 'σ' ''',
    zig_impl=r'''// std 0.16 no trae tablas de mapeo de caso Unicode: std.ascii.toLower/toUpper/
// lowerString/upperString/eqlIgnoreCase solo tocan A-Z/a-z, y std.unicode solo
// ofrece codificacion/decodificacion UTF-8/16/WTF-8 (utf8Decode, Utf8View...).
// Para cubrir Unicode hay que depender de una libreria externa (p. ej. ziglyph/
// zg) o generar tablas de UnicodeData.txt/SpecialCasing.txt, y tratar los casos
// que cambian de longitud (ss, i con punto) y los sensibles al contexto (sigma final).
// NO verificado en gate: no hay API std que demostrar.''',
    zig_test=None,
    apis_used=["std.ascii.toLower","std.ascii.toUpper","std.unicode.utf8Decode"],
    constraints=["requiere dependencia externa o tablas propias"],
    preconditions=["texto UTF-8 valido"],
    postconditions=["N/D"],
    side_effects=[],
    error_behavior="N/D",
    ownership_memory="N/D",
    differences=["la std solo mapea ASCII (ver ascii-case-lower-upper)","el mapeo Unicode cambia longitudes (ss) y depende del contexto (sigma final), casefold distinto de lower"],
    provenance="NO_GATE: la std 0.16 no tiene mapeo de caso Unicode (comprobado con ziggrep en lib/std/unicode.zig y ascii.zig)",
    status="NOT_DEMONSTRATED",
    entry_type="gap",
),
]

CONTRACTS = {
    "zig0.16/base64-encode-decode": _c(None, None, None, [],
        type_sig={"input": "bytes/str", "output": "bytes/str/numero o error"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/hex-encode-decode": _c(None, None, None, [],
        type_sig={"input": "bytes/str", "output": "bytes/str/numero o error"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/parse-int-base-overflow": _c(None, None, None, [],
        type_sig={"input": "bytes/str", "output": "bytes/str/numero o error"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/parse-float-format-decimals": _c(None, None, None, [],
        type_sig={"input": "bytes/str", "output": "bytes/str/numero o error"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/str-find-replace-affix": _c(None, None, None, [],
        type_sig={"input": "bytes/str", "output": "bytes/str/numero o error"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/utf8-codepoints-validate": _c(None, None, None, [],
        type_sig={"input": "bytes/str", "output": "bytes/str/numero o error"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/ascii-case-lower-upper": _c(None, None, None, [],
        type_sig={"input": "bytes/str", "output": "bytes/str/numero o error"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/unicode-case-mapping": _c(None, None, None, [],
        type_sig={"input": "bytes/str", "output": "bytes/str/numero o error"},
        skip_reason="sin driver diferencial todavia"),
}
