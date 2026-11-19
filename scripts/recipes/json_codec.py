from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"; PY = "3.12"; PROV = "std local de zig 0.16.0 (repo en lib/std)"

ENTRIES = [
    dict(
        operation_id='zig0.16/json-loads-dynamic',
        name='json.loads a valor dinamico (std.json.Value)',
        intent='Decodificar un texto JSON de forma dinamica, sin conocer el esquema, a un arbol de valores (dict/list/str/int/float/bool/None) que se recorre con switch o acceso por clave.',
        aliases=['json.loads', 'json.load', 'loads', 'parsear json', 'decode json', 'dict desde json', 'std.json.Value', 'parseFromSlice', 'json dinamico', 'json sin esquema', 'parse json string to dynamic value', 'parse JSON without a schema', 'leer json como diccionario', 'jsonlib loads', 'estructura de datos generica desde json'],
        source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=r'''import json
d = json.loads('{"a":1,"b":[true,null,2.5],"s":"hi"}')
d["a"], d["b"][2], d["s"], d.get("zz")''',
        zig_impl=r'''pub fn loadsDynamic(gpa: std.mem.Allocator, text: []const u8) !std.json.Parsed(std.json.Value) {
    return std.json.parseFromSlice(std.json.Value, gpa, text, .{});
}

pub fn getKey(v: std.json.Value, key: []const u8) ?std.json.Value {
    if (v != .object) return null;
    return v.object.get(key);
}''',
        zig_test=r'''const std = @import("std");

pub fn loadsDynamic(gpa: std.mem.Allocator, text: []const u8) !std.json.Parsed(std.json.Value) {
    return std.json.parseFromSlice(std.json.Value, gpa, text, .{});
}

pub fn getKey(v: std.json.Value, key: []const u8) ?std.json.Value {
    if (v != .object) return null;
    return v.object.get(key);
}

test "objeto, arrays y tipos de valor" {
    const parsed = try loadsDynamic(std.testing.allocator, "{\"a\":1,\"b\":[true,null,2.5],\"s\":\"hi\"}");
    defer parsed.deinit();
    try std.testing.expectEqual(@as(i64, 1), getKey(parsed.value, "a").?.integer);
    const b = getKey(parsed.value, "b").?.array;
    try std.testing.expectEqual(@as(usize, 3), b.items.len);
    try std.testing.expect(b.items[0].bool);
    try std.testing.expect(b.items[1] == .null);
    try std.testing.expectEqual(@as(f64, 2.5), b.items[2].float);
    try std.testing.expectEqualStrings("hi", getKey(parsed.value, "s").?.string);
    try std.testing.expect(getKey(parsed.value, "no-existe") == null);
}

test "la raiz puede ser un escalar y getKey devuelve null" {
    const parsed = try loadsDynamic(std.testing.allocator, "42");
    defer parsed.deinit();
    try std.testing.expectEqual(@as(i64, 42), parsed.value.integer);
    try std.testing.expect(getKey(parsed.value, "x") == null);
}

test "entero fuera de i64 queda como number_string" {
    const parsed = try loadsDynamic(std.testing.allocator, "[12345678901234567890]");
    defer parsed.deinit();
    try std.testing.expectEqualStrings("12345678901234567890", parsed.value.array.items[0].number_string);
}

test "claves duplicadas son error (Python se queda con la ultima)" {
    try std.testing.expectError(error.DuplicateField, loadsDynamic(std.testing.allocator, "{\"a\":1,\"a\":2}"));
}

test "el orden de las claves se conserva" {
    const parsed = try loadsDynamic(std.testing.allocator, "{\"z\":1,\"a\":2}");
    defer parsed.deinit();
    const keys = parsed.value.object.keys();
    try std.testing.expectEqualStrings("z", keys[0]);
    try std.testing.expectEqualStrings("a", keys[1]);
}''',
        apis_used=['std.json.parseFromSlice', 'std.json.Parsed', 'std.json.Value', 'std.json.ObjectMap.get'],
        constraints=['gpa propio', 'sin root'],
        preconditions=['texto en memoria'],
        postconditions=['Parsed.value valido hasta Parsed.deinit()'],
        side_effects=[],
        error_behavior='error.SyntaxError, error.UnexpectedEndOfInput, error.DuplicateField, error.OutOfMemory (sin excepciones).',
        ownership_memory='parseFromSlice reserva un arena; Parsed.deinit() libera todo. Con las opciones por defecto los strings sin escapes pueden apuntar al buffer de entrada: el texto debe vivir mientras viva Parsed (o usar .allocate = .alloc_always).',
        differences=['Python: claves duplicadas, gana la ultima; Zig: error.DuplicateField (por defecto, tambien en Value)', 'Python: enteros de precision arbitraria; Zig: i64, y si no cabe queda como Value.number_string', 'Python acepta NaN/Infinity/-Infinity; Zig da error.SyntaxError', 'Value distingue .integer/.float/.number_string; Python int/float', "el valor es un union(enum): hay que hacer switch o comprobar la etiqueta, no hay indexado dinamico d['a']['b']", 'con alloc_if_needed (defecto) los strings pueden ser slices del texto de entrada'],
        provenance=PROV,
    ),
    dict(
        operation_id='zig0.16/json-loads-typed-struct',
        name='json.loads a struct tipado con opcionales y campos extra',
        intent='Decodificar JSON directamente a un struct Zig con valores por defecto, campos opcionales, y politica explicita ante campos desconocidos (equivalente a dataclass/pydantic).',
        aliases=['dataclass from json', 'pydantic parse', 'json.loads **kwargs', 'TypedDict', 'parseFromSlice struct', 'campos opcionales json', 'ignore_unknown_fields', 'unknown fields', 'json a struct', 'deserializar json', 'json a dataclass', 'valores por defecto json', 'validar esquema json', 'decode json into typed struct'],
        source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=r'''import json
from dataclasses import dataclass
from typing import Optional

@dataclass
class Config:
    name: str
    port: int = 8080
    debug: Optional[bool] = None

d = json.loads('{"name":"srv","extra":1}')
cfg = Config(**{k: v for k, v in d.items() if k in Config.__dataclass_fields__})''',
        zig_impl=r'''pub const Config = struct {
    name: []const u8,
    port: u16 = 8080,
    debug: ?bool = null,
};

pub fn loadsConfig(gpa: std.mem.Allocator, text: []const u8, strict: bool) !std.json.Parsed(Config) {
    return std.json.parseFromSlice(Config, gpa, text, .{
        .ignore_unknown_fields = !strict,
    });
}''',
        zig_test=r'''const std = @import("std");

pub const Config = struct {
    name: []const u8,
    port: u16 = 8080,
    debug: ?bool = null,
};

pub fn loadsConfig(gpa: std.mem.Allocator, text: []const u8, strict: bool) !std.json.Parsed(Config) {
    return std.json.parseFromSlice(Config, gpa, text, .{
        .ignore_unknown_fields = !strict,
    });
}

test "defaults y opcionales ausentes" {
    const p = try loadsConfig(std.testing.allocator, "{\"name\":\"srv\"}", false);
    defer p.deinit();
    try std.testing.expectEqualStrings("srv", p.value.name);
    try std.testing.expectEqual(@as(u16, 8080), p.value.port);
    try std.testing.expect(p.value.debug == null);
}

test "valores presentes y campo desconocido ignorado" {
    const p = try loadsConfig(std.testing.allocator, "{\"name\":\"a\",\"port\":9000,\"debug\":true,\"extra\":[1,2]}", false);
    defer p.deinit();
    try std.testing.expectEqual(@as(u16, 9000), p.value.port);
    try std.testing.expectEqual(true, p.value.debug.?);
}

test "modo estricto rechaza campos desconocidos" {
    try std.testing.expectError(error.UnknownField, loadsConfig(std.testing.allocator, "{\"name\":\"a\",\"extra\":1}", true));
}

test "campo obligatorio ausente" {
    try std.testing.expectError(error.MissingField, loadsConfig(std.testing.allocator, "{\"port\":1}", false));
}

test "tipo equivocado y fuera de rango" {
    try std.testing.expectError(error.UnexpectedToken, loadsConfig(std.testing.allocator, "{\"name\":null}", false));
    try std.testing.expectError(error.UnexpectedToken, loadsConfig(std.testing.allocator, "[1]", false));
    try std.testing.expectError(error.Overflow, loadsConfig(std.testing.allocator, "{\"name\":\"a\",\"port\":70000}", false));
    try std.testing.expectError(error.Overflow, loadsConfig(std.testing.allocator, "{\"name\":\"a\",\"port\":-1}", false));
    try std.testing.expectError(error.InvalidNumber, loadsConfig(std.testing.allocator, "{\"name\":\"a\",\"port\":1.5}", false));
}''',
        apis_used=['std.json.parseFromSlice', 'std.json.ParseOptions.ignore_unknown_fields', 'std.json.Parsed'],
        constraints=['gpa propio'],
        preconditions=['T es un struct/union/slice/escalar soportado por std.json'],
        postconditions=['Parsed.value valido hasta Parsed.deinit()'],
        side_effects=[],
        error_behavior='error.MissingField, error.UnknownField (modo estricto), error.DuplicateField, error.UnexpectedToken (tipo equivocado), error.Overflow (fuera de rango del entero), error.InvalidNumber (1.5 en un entero).',
        ownership_memory='Parsed.deinit() libera el arena con name y demas slices; no liberar los campos por separado.',
        differences=["Python no valida tipos: Config(port='x') no falla; Zig valida tipo y rango al decodificar", 'campo obligatorio ausente es error.MissingField (Python: TypeError del constructor)', 'los opcionales ?T aceptan null explicito y ausencia; un tipo no opcional con null da error.UnexpectedToken', 'por defecto un campo desconocido es error.UnknownField; hay que pedir ignore_unknown_fields=true', 'un entero con valor cadena numerica ("80") se acepta en std.json para campos enteros; Python lo dejaria como str', 'error.Overflow para u16 con 70000 o -1'],
        provenance=PROV,
    ),
    dict(
        operation_id='zig0.16/json-dumps-indent',
        name='json.dumps compacto o indentado',
        intent='Serializar un valor Zig (struct, array, optional, std.json.Value) a texto JSON, en una sola linea o indentado.',
        aliases=['json.dumps', 'dumps', 'indent=2', 'separators', 'json.dump', 'stringify', 'std.json.Stringify', 'valueAlloc', 'serializar a json', 'pretty print json', 'json bonito', 'convertir struct a json', 'encode json', 'imprimir json indentado', 'json compacto minificado'],
        source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=r'''import json
json.dumps({"id": 7, "tag": "x"}, separators=(",", ":"))
json.dumps({"xs": [1, 2], "empty": []}, indent=2)''',
        zig_impl=r'''pub fn dumps(gpa: std.mem.Allocator, v: anytype, pretty: bool) ![]u8 {
    return std.json.Stringify.valueAlloc(gpa, v, .{
        .whitespace = if (pretty) .indent_2 else .minified,
    });
}''',
        zig_test=r'''const std = @import("std");

pub fn dumps(gpa: std.mem.Allocator, v: anytype, pretty: bool) ![]u8 {
    return std.json.Stringify.valueAlloc(gpa, v, .{
        .whitespace = if (pretty) .indent_2 else .minified,
    });
}

const Item = struct { id: u32, tag: ?[]const u8 = null, ok: bool };

test "compacto: sin espacios, orden de declaracion" {
    const out = try dumps(std.testing.allocator, Item{ .id = 7, .tag = "x", .ok = true }, false);
    defer std.testing.allocator.free(out);
    try std.testing.expectEqualStrings("{\"id\":7,\"tag\":\"x\",\"ok\":true}", out);
}

test "null opcional se emite como null" {
    const out = try dumps(std.testing.allocator, Item{ .id = 1, .ok = false }, false);
    defer std.testing.allocator.free(out);
    try std.testing.expectEqualStrings("{\"id\":1,\"tag\":null,\"ok\":false}", out);
}

test "indentado de 2 espacios (indent=2)" {
    const items = [_]u32{ 1, 2 };
    const out = try dumps(std.testing.allocator, .{ .xs = items, .empty = [0]u32{} }, true);
    defer std.testing.allocator.free(out);
    try std.testing.expectEqualStrings(
        "{\n  \"xs\": [\n    1,\n    2\n  ],\n  \"empty\": []\n}",
        out,
    );
}

test "floats: 1.0 se emite como 1" {
    const out = try dumps(std.testing.allocator, [_]f64{ 1.0, 2.5 }, false);
    defer std.testing.allocator.free(out);
    try std.testing.expectEqualStrings("[1,2.5]", out);
}

test "std.json.Value se puede volver a serializar" {
    const parsed = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, "{\"b\":[1,{\"c\":null}],\"a\":\"x\"}", .{});
    defer parsed.deinit();
    const out = try dumps(std.testing.allocator, parsed.value, false);
    defer std.testing.allocator.free(out);
    try std.testing.expectEqualStrings("{\"b\":[1,{\"c\":null}],\"a\":\"x\"}", out);
}''',
        apis_used=['std.json.Stringify.valueAlloc', 'std.json.Stringify.Options.whitespace', 'std.json.Value'],
        constraints=['gpa propio'],
        preconditions=['valor serializable por std.json'],
        postconditions=['slice owned por el caller'],
        side_effects=[],
        error_behavior='error.OutOfMemory unicamente.',
        ownership_memory='valueAlloc devuelve un slice que el caller libera con gpa.free.',
        differences=["el modo por defecto de Zig es minificado (equivale a separators=(',',':')), el de Python usa ', ' y ': '", 'indent_2 deja arrays vacios como [] igual que Python indent=2', 'el orden de claves es el de declaracion del struct; Python no ordena salvo sort_keys=True (no existe en Zig)', 'campos ?T con null se emiten como null (emit_null_optional_fields=true)', 'float 1.0 se emite como 1 (Python: 1.0); 1e20 se emite como 100000000000000000000 (Python: 1e+20)', '[N]u8 y []const u8 se emiten como string, no como lista de numeros, salvo emit_strings_as_arrays'],
        provenance=PROV,
    ),
    dict(
        operation_id='zig0.16/json-invalid-input-error',
        name='manejar JSON invalido (JSONDecodeError)',
        intent='Detectar y clasificar JSON malformado, truncado o con claves duplicadas sin abortar, equivalente a try/except json.JSONDecodeError; o solo validar.',
        aliases=['JSONDecodeError', 'json.JSONDecodeError', 'try except json', 'json invalido', 'json malformado', 'validar json', 'is valid json', 'std.json.validate', 'SyntaxError', 'UnexpectedEndOfInput', 'json truncado', 'comprobar si un texto es json', 'catch parse error', 'Expecting value', 'extra data', 'json valido o no', 'parsear sin que el programa falle'],
        source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=r'''import json
def check(text):
    try:
        json.loads(text)
        return "ok"
    except json.JSONDecodeError as e:
        return "truncated" if e.msg.startswith("Expecting") and e.pos >= len(text.rstrip()) else "syntax"''',
        zig_impl=r'''pub const Check = enum { ok, truncated, syntax, other };

/// Equivalente a try/except json.JSONDecodeError: clasifica el fallo.
pub fn check(gpa: std.mem.Allocator, text: []const u8) !Check {
    const parsed = std.json.parseFromSlice(std.json.Value, gpa, text, .{}) catch |err| switch (err) {
        error.OutOfMemory => return err,
        error.UnexpectedEndOfInput => return .truncated,
        error.SyntaxError => return .syntax,
        else => return .other,
    };
    parsed.deinit();
    return .ok;
}

/// Solo validez (sin construir el arbol).
pub fn isValid(gpa: std.mem.Allocator, text: []const u8) !bool {
    return std.json.validate(gpa, text);
}''',
        zig_test=r'''const std = @import("std");

pub const Check = enum { ok, truncated, syntax, other };

/// Equivalente a try/except json.JSONDecodeError: clasifica el fallo.
pub fn check(gpa: std.mem.Allocator, text: []const u8) !Check {
    const parsed = std.json.parseFromSlice(std.json.Value, gpa, text, .{}) catch |err| switch (err) {
        error.OutOfMemory => return err,
        error.UnexpectedEndOfInput => return .truncated,
        error.SyntaxError => return .syntax,
        else => return .other,
    };
    parsed.deinit();
    return .ok;
}

/// Solo validez (sin construir el arbol).
pub fn isValid(gpa: std.mem.Allocator, text: []const u8) !bool {
    return std.json.validate(gpa, text);
}

test "documentos validos" {
    const a = std.testing.allocator;
    try std.testing.expectEqual(Check.ok, try check(a, "{\"a\":[1,2]}"));
    try std.testing.expectEqual(Check.ok, try check(a, "  null "));
    try std.testing.expect(try isValid(a, "[1,2]"));
}

test "entrada truncada o vacia" {
    const a = std.testing.allocator;
    try std.testing.expectEqual(Check.truncated, try check(a, ""));
    try std.testing.expectEqual(Check.truncated, try check(a, "{\"a\":"));
    try std.testing.expectEqual(Check.truncated, try check(a, "[1,2"));
    try std.testing.expect(!try isValid(a, "[1,2"));
}

test "errores de sintaxis" {
    const a = std.testing.allocator;
    const bad = [_][]const u8{ "{\"a\":1,}", "[1,]", "nope", "{'a':1}", "01", "NaN", "{} x", "[1]]", "\"a\tb\"", "\"\\x\"" };
    for (bad) |s| {
        try std.testing.expectEqual(Check.syntax, try check(a, s));
        try std.testing.expect(!try isValid(a, s));
    }
}

test "claves duplicadas caen en other (DuplicateField)" {
    try std.testing.expectEqual(Check.other, try check(std.testing.allocator, "{\"a\":1,\"a\":2}"));
}''',
        apis_used=['std.json.parseFromSlice', 'std.json.validate', 'error.SyntaxError', 'error.UnexpectedEndOfInput'],
        constraints=['gpa propio'],
        preconditions=['texto arbitrario'],
        postconditions=['Check clasifica el resultado; OutOfMemory se propaga'],
        side_effects=[],
        error_behavior='No lanza por JSON malo: lo traduce a Check; solo propaga error.OutOfMemory. Los errores del parser son SyntaxError, UnexpectedEndOfInput (truncado/vacio), DuplicateField.',
        ownership_memory='check libera el Parsed inmediatamente; validate no construye arbol.',
        differences=['Zig no da posicion (pos/lineno/colno) en parseFromSlice; JSONDecodeError si', "Zig solo distingue SyntaxError y UnexpectedEndOfInput; Python da mensajes ('Expecting value', 'Extra data', ...)", "texto vacio: Python 'Expecting value', Zig UnexpectedEndOfInput", "datos tras el valor ('{} x', '[1]]', '01'): Python 'Extra data', Zig SyntaxError", 'Python acepta NaN; Zig lo rechaza', 'claves duplicadas: Python no falla (gana la ultima); Zig da DuplicateField', 'validate solo comprueba sintaxis; no detecta claves duplicadas'],
        provenance=PROV,
    ),
    dict(
        operation_id='zig0.16/json-string-escape-unicode',
        name='escapes y unicode en strings JSON',
        intent='Escapar un string a literal JSON (comillas, backslash, control, ensure_ascii con pares sustitutos) y decodificar un literal con \\uXXXX a bytes UTF-8.',
        aliases=['ensure_ascii', 'json.dumps string', 'escape json', 'escapar comillas json', 'unicode escape \\u', 'surrogate pair', 'par sustituto', 'json quote', 'unquote json string', 'utf-8 json', 'caracteres especiales json', 'escape_unicode', 'json string literal', 'encodeJsonString', 'acentos y emoji en json', 'json solo ascii'],
        source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=r'''import json
json.dumps("a\"b\\c\n\t/\x01")
json.dumps("é😀")
json.dumps("é😀", ensure_ascii=False)
json.loads('"\\u00e9\\ud83d\\ude00"')''',
        zig_impl=r'''/// json.dumps(s, ensure_ascii=...) para un string suelto.
pub fn quote(gpa: std.mem.Allocator, s: []const u8, ensure_ascii: bool) ![]u8 {
    return std.json.Stringify.valueAlloc(gpa, s, .{ .escape_unicode = ensure_ascii });
}

/// json.loads de un literal string: devuelve los bytes UTF-8 decodificados.
pub fn unquote(gpa: std.mem.Allocator, literal: []const u8) ![]u8 {
    const parsed = try std.json.parseFromSlice([]const u8, gpa, literal, .{});
    defer parsed.deinit();
    return gpa.dupe(u8, parsed.value);
}''',
        zig_test=r'''const std = @import("std");

/// json.dumps(s, ensure_ascii=...) para un string suelto.
pub fn quote(gpa: std.mem.Allocator, s: []const u8, ensure_ascii: bool) ![]u8 {
    return std.json.Stringify.valueAlloc(gpa, s, .{ .escape_unicode = ensure_ascii });
}

/// json.loads de un literal string: devuelve los bytes UTF-8 decodificados.
pub fn unquote(gpa: std.mem.Allocator, literal: []const u8) ![]u8 {
    const parsed = try std.json.parseFromSlice([]const u8, gpa, literal, .{});
    defer parsed.deinit();
    return gpa.dupe(u8, parsed.value);
}

test "escapes basicos" {
    const a = std.testing.allocator;
    const out = try quote(a, "a\"b\\c\n\t/\x01", false);
    defer a.free(out);
    try std.testing.expectEqualStrings("\"a\\\"b\\\\c\\n\\t/\\u0001\"", out);
}

test "unicode crudo vs ensure_ascii" {
    const a = std.testing.allocator;
    const raw = try quote(a, "é😀", false);
    defer a.free(raw);
    try std.testing.expectEqualStrings("\"é😀\"", raw);
    const esc = try quote(a, "é😀", true);
    defer a.free(esc);
    try std.testing.expectEqualStrings("\"\\u00e9\\ud83d\\ude00\"", esc);
}

test "unquote decodifica \\u y pares sustitutos a UTF-8" {
    const a = std.testing.allocator;
    const got = try unquote(a, "\"\\u00e9\\ud83d\\ude00\\n\"");
    defer a.free(got);
    try std.testing.expectEqualStrings("é😀\n", got);
}

test "ida y vuelta" {
    const a = std.testing.allocator;
    const q = try quote(a, "línea\n\"x\" ñ", true);
    defer a.free(q);
    const back = try unquote(a, q);
    defer a.free(back);
    try std.testing.expectEqualStrings("línea\n\"x\" ñ", back);
}

test "surrogate suelto y escape invalido son SyntaxError" {
    const a = std.testing.allocator;
    try std.testing.expectError(error.SyntaxError, unquote(a, "\"\\ud800\""));
    try std.testing.expectError(error.SyntaxError, unquote(a, "\"\\u00zz\""));
    try std.testing.expectError(error.SyntaxError, unquote(a, "\"\\x\""));
}''',
        apis_used=['std.json.Stringify.valueAlloc', 'std.json.Stringify.Options.escape_unicode', 'std.json.parseFromSlice'],
        constraints=['gpa propio'],
        preconditions=['entrada UTF-8 valida para quote'],
        postconditions=['slices owned por el caller'],
        side_effects=[],
        error_behavior='unquote: error.SyntaxError ante escape invalido, \\u mal formado o sustituto suelto; error.UnexpectedToken si el literal no es string.',
        ownership_memory='quote y unquote devuelven slices owned por el caller; unquote duplica antes de liberar el Parsed.',
        differences=['Python ensure_ascii=True es el defecto; en Zig escape_unicode es false por defecto', 'los \\u de salida van en minuscula en ambos', "'/' no se escapa en ninguno", "un sustituto suelto '\\ud800': Python lo acepta (str con surrogate); Zig da error.SyntaxError", 'Zig opera sobre bytes UTF-8; un slice []u8 no-UTF-8 se emite como array de numeros en vez de string', 'caracteres de control: ambos usan \\n \\t etc. y \\u00XX para el resto'],
        provenance=PROV,
    ),
    dict(
        operation_id='zig0.16/json-read-file-limited',
        name='leer un archivo JSON con limite de tamano',
        intent='Cargar y decodificar un archivo JSON de disco rechazando archivos que superen un limite de bytes (json.load con tope).',
        aliases=['json.load', 'open json file', 'read json file', 'leer archivo json', 'cargar config json', 'limite de tamano json', 'json file size limit', 'readFileAlloc json', 'StreamTooLong', 'json.load(open(...))', 'Path.read_text json.loads', 'archivo json grande', 'load json from disk'],
        source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=r'''import json
from pathlib import Path

def load(path, max_bytes):
    with open(path, "rb") as f:
        data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("too big")
    return json.loads(data)''',
        zig_impl=r'''pub fn loadJsonFile(
    comptime T: type,
    gpa: std.mem.Allocator,
    io: std.Io,
    dir: std.Io.Dir,
    sub_path: []const u8,
    max_bytes: usize,
) !std.json.Parsed(T) {
    const bytes = try dir.readFileAlloc(io, sub_path, gpa, .limited(max_bytes));
    defer gpa.free(bytes);
    // Sin .alloc_always los strings sin escapes apuntan DENTRO de `bytes`
    // (alloc_if_needed) y quedarian colgando al liberarlo.
    return std.json.parseFromSlice(T, gpa, bytes, .{
        .ignore_unknown_fields = true,
        .allocate = .alloc_always,
    });
}''',
        zig_test=r'''const std = @import("std");

pub fn loadJsonFile(
    comptime T: type,
    gpa: std.mem.Allocator,
    io: std.Io,
    dir: std.Io.Dir,
    sub_path: []const u8,
    max_bytes: usize,
) !std.json.Parsed(T) {
    const bytes = try dir.readFileAlloc(io, sub_path, gpa, .limited(max_bytes));
    defer gpa.free(bytes);
    // Sin .alloc_always los strings sin escapes apuntan DENTRO de `bytes`
    // (alloc_if_needed) y quedarian colgando al liberarlo.
    return std.json.parseFromSlice(T, gpa, bytes, .{
        .ignore_unknown_fields = true,
        .allocate = .alloc_always,
    });
}

const Cfg = struct { name: []const u8, n: u32 = 0 };

test "lee y decodifica un archivo JSON" {
    const a = std.testing.allocator;
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "c.json", .data = "{\"name\":\"x\",\"n\":5,\"otro\":true}" });
    const p = try loadJsonFile(Cfg, a, io, tmp.dir, "c.json", 1024);
    defer p.deinit();
    try std.testing.expectEqualStrings("x", p.value.name);
    try std.testing.expectEqual(@as(u32, 5), p.value.n);
}

test "archivo ausente da FileNotFound" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try std.testing.expectError(error.FileNotFound, loadJsonFile(Cfg, std.testing.allocator, std.testing.io, tmp.dir, "no.json", 1024));
}

test "archivo mayor que el limite da StreamTooLong" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "c.json", .data = "{\"name\":\"x\",\"n\":5}" });
    try std.testing.expectError(error.StreamTooLong, loadJsonFile(Cfg, std.testing.allocator, io, tmp.dir, "c.json", 4));
}

test "contenido invalido da error de sintaxis" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "c.json", .data = "{nope" });
    try std.testing.expectError(error.SyntaxError, loadJsonFile(Cfg, std.testing.allocator, io, tmp.dir, "c.json", 1024));
}''',
        apis_used=['std.Io.Dir.readFileAlloc', 'Io.Limit.limited', 'std.json.parseFromSlice', 'std.testing.tmpDir'],
        constraints=['gpa propio', 'sin root'],
        preconditions=['dir abierto (cwd, openDirAbsolute o tmpDir)'],
        postconditions=['Parsed.value valido hasta deinit; el buffer del archivo ya se libero'],
        side_effects=['lectura de archivo'],
        error_behavior='error.FileNotFound, error.StreamTooLong (archivo >= limite), error.SyntaxError/UnexpectedEndOfInput (JSON malo), error.OutOfMemory.',
        ownership_memory='El buffer del archivo se libera dentro de la funcion; por eso se usa .allocate = .alloc_always: sin ello los strings apuntarian al buffer liberado (use-after-free).',
        differences=['Python no tiene limite por defecto; aqui el limite es obligatorio y dispara StreamTooLong', 'std.fs.cwd().readFileAlloc ya no existe: es std.Io.Dir.readFileAlloc(io, path, gpa, .limited(n))', 'el limite es exclusivo en el sentido de que alcanzarlo ya da StreamTooLong; usar un tope holgado', 'json.load decodifica bytes UTF-8/16/32 con BOM; Zig espera UTF-8 sin BOM', 'FileNotFoundError de Python es error.FileNotFound', 'no liberar el buffer antes de parsear sin alloc_always si T contiene slices'],
        provenance=PROV,
    ),
]

CONTRACTS = {
    "zig0.16/json-loads-dynamic": _c(None, None, None, [],
        type_sig={"input": 'texto JSON ([]const u8)', "output": 'std.json.Parsed(std.json.Value)'},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/json-loads-typed-struct": _c(None, None, None, [],
        type_sig={"input": 'texto JSON + struct tipado', "output": 'std.json.Parsed(Config)'},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/json-dumps-indent": _c(None, None, None, [],
        type_sig={"input": 'valor Zig', "output": '[]u8 (JSON)'},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/json-invalid-input-error": _c(None, None, None, [],
        type_sig={"input": 'texto ([]const u8)', "output": 'Check (ok|truncated|syntax|other)'},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/json-string-escape-unicode": _c(None, None, None, [],
        type_sig={"input": 'string UTF-8 o literal JSON', "output": '[]u8'},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/json-read-file-limited": _c(None, None, None, [],
        type_sig={"input": '(Dir, ruta, max_bytes)', "output": 'std.json.Parsed(T)'},
        skip_reason="sin driver diferencial todavia"),
}
