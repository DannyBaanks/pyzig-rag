// Case generators: one schema per fuzzable operation.
//
// Every generator is a pure function of (schema, seed stream): the same seed
// always yields byte-identical cases. The alphabet is boundary-biased
// (empty, 1 byte, max, off-by-one) because that is where semantics break.
//
// A case is a sequence of length-prefixed fields (see proto.zig). The layout
// of each schema is documented in the corpus contract (`fuzz.schema_version`)
// and mirrored by the Python reference models:
//
//   argv/v1     [prog, arg...]
//   kv/v1       [text]
//   read/v1     [path, present, content, limit]     present: 0=ausente 1=archivo 2=dir
//   write/v1    [mode, pre, data]                   mode: truncate | append
//   exists/v1   [kind, path]                        kind: file | missing | dir
//   splitfmt/v1 [sep, text, mac, ip, width]
//   sleep/v1    [ms]
//   env/v1      [key]
//   spawn/v1    [pre, prog, arg...]
//   stdout/v1   [stream, msg]                       stream: out | err
//   sha256/v1   [data]
//   base64/v1   [op, data]                          op: enc | dec
//   hex/v1      [op, data]                          op: enc | dec
//   parseint/v1 [text, base]                        base: 0 o 2..36 (otra: invalid)
//   divmod/v1   [a, b]                              enteros i32 decimales; b=0 -> err
//   bits/v1     [op, text]                          op: count | length; text: i64 decimal
//   packint/v1  [op, endian, value, offset, data]   op: pack | read | readi | write
//   pipe/v1     [data]                              (reservado para pipelines, F2)
const std = @import("std");
const proto = @import("proto.zig");
const rngmod = @import("rng.zig");

const Rng = rngmod.Rng;

pub const Schema = enum {
    argv,
    kv,
    read,
    write,
    exists,
    splitfmt,
    sleep,
    env,
    spawn,
    stdout,
    sha256,
    base64,
    hex,
    parseint,
    divmod,
    bits,
    packint,
    pipe,

    pub fn fromName(s: []const u8) ?Schema {
        inline for (@typeInfo(Schema).@"enum".fields) |f| {
            if (std.mem.eql(u8, s, f.name)) return @enumFromInt(f.value);
        }
        return null;
    }

    pub fn name(self: Schema) []const u8 {
        return @tagName(self);
    }
};

/// Command templates used by argv/v1 and spawn/v1. Only programs that exist
/// in the sandbox image (or a deliberately missing one) are used.
const COMMANDS = [_][]const []const u8{
    &.{ "printf", "%s", "hola" },
    &.{ "printf", "%s", "" },
    &.{ "printf", "%s", "con espacios y \xc3\xb1" },
    &.{ "true" },
    &.{ "false" },
    &.{ "sh", "-c", "exit 0" },
    &.{ "sh", "-c", "exit 3" },
    &.{ "sh", "-c", "echo out; echo err >&2; exit 7" },
    &.{ "sh", "-c", "kill -TERM $$" },
    &.{ "sh", "-c", "printf 'x%.0s' $(seq 1 70000)" },
    &.{ "sh", "-c", "printf 'y%.0s' $(seq 1 65536)" },
    &.{ "sh", "-c", "printf 'z%.0s' $(seq 1 65535)" },
    &.{ "no-such-cmd-xyz" },
};

const KV_KEYS = [_][]const u8{ "SSID", "PSK", "A", "KEY_1", "k-2", "x", "" };
const KV_VALUES = [_][]const u8{
    "mi red",
    "'citada'",
    "''",
    "a=b",
    "  con espacios  ",
    "",
    "comilla' dentro",
    "sin cerrar'",
    "\xc3\xb1and\u{fc}",
};

fn asciiPrintable() []const u8 {
    return "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./ ";
}

/// Random bytes with a readable bias plus occasional NUL/high bytes.
fn randomBytes(r: *Rng, out: []u8) void {
    for (out) |*b| {
        if (r.chance(1, 16)) {
            b.* = r.pick(u8, "\x00\x0a\x0d\t\x7f\xff");
        } else {
            b.* = r.pick(u8, asciiPrintable());
        }
    }
}

fn decimal(gpa: std.mem.Allocator, value: usize) ![]const u8 {
    return std.fmt.allocPrint(gpa, "{d}", .{value});
}

/// One in N cases is deliberately malformed: both sides must reject it the
/// same way (status `invalid`), which is itself a comparison.
fn maybeInvalid(r: *Rng) bool {
    return r.chance(1, 16);
}

fn genArgv(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var fields: std.ArrayList([]const u8) = .empty;
    defer fields.deinit(gpa);
    const tmpl = r.pick([]const []const u8, &COMMANDS);
    for (tmpl) |arg| try fields.append(gpa, arg);
    // occasional extra argument with hostile content
    if (r.chance(1, 4)) {
        var buf: [64]u8 = undefined;
        const n = r.boundaryLen(buf.len);
        randomBytes(r, buf[0..n]);
        try fields.append(gpa, buf[0..n]);
    }
    const payload = try proto.packFields(gpa, fields.items);
    return payload;
}

fn genKv(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var text: std.ArrayList(u8) = .empty;
    defer text.deinit(gpa);
    const lines = r.boundaryLen(6);
    var i: usize = 0;
    while (i < lines) : (i += 1) {
        switch (r.below(10)) {
            0 => try text.appendSlice(gpa, "# comentario\n"),
            1 => try text.appendSlice(gpa, "\n"),
            2 => try text.appendSlice(gpa, "sin-igual\n"),
            3 => try text.appendSlice(gpa, "  clave  =  valor  \n"),
            4 => {
                try text.appendSlice(gpa, r.pick([]const u8, &KV_KEYS));
                try text.appendSlice(gpa, "=");
                try text.appendSlice(gpa, r.pick([]const u8, &KV_VALUES));
                try text.appendSlice(gpa, if (r.chance(1, 3)) "\r\n" else "\n");
            },
            5 => try text.append(gpa, 0),
            6 => try text.appendSlice(gpa, "=solo-igual\n"),
            else => {
                var buf: [48]u8 = undefined;
                const n = r.boundaryLen(buf.len);
                randomBytes(r, buf[0..n]);
                try text.appendSlice(gpa, buf[0..n]);
                try text.append(gpa, '\n');
            },
        }
    }
    const payload = try proto.packFields(gpa, &.{text.items});
    return payload;
}

fn genRead(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    const PathKind = struct { path: []const u8, present: []const u8 };
    const paths = [_]PathKind{
        .{ .path = "f.txt", .present = "1" },
        .{ .path = "sub/g.txt", .present = "1" },
        .{ .path = "missing.txt", .present = "0" },
        .{ .path = "dir", .present = "2" },
    };
    const p = r.pick(PathKind, &paths);
    var content: [8192]u8 = undefined;
    const len = switch (r.below(8)) {
        0 => 0,
        1 => 1,
        2 => 4,
        3 => 4096,
        else => r.boundaryLen(64),
    };
    randomBytes(r, content[0..len]);
    const limit: usize = switch (r.below(10)) {
        0 => 0,
        1 => 1,
        2 => len,
        3 => len + 1,
        4 => if (len > 0) len - 1 else 0,
        5 => 65536,
        else => r.boundaryLen(4096),
    };
    var limit_buf: [32]u8 = undefined;
    const limit_str: []const u8 = if (maybeInvalid(r))
        "no-es-un-numero"
    else
        try std.fmt.bufPrint(&limit_buf, "{d}", .{limit});
    const payload = try proto.packFields(gpa, &.{ p.path, p.present, content[0..len], limit_str });
    return payload;
}

fn genWrite(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    const mode = switch (r.below(3)) {
        0 => "truncate",
        1 => "append",
        else => if (maybeInvalid(r)) "modo-inexistente" else "truncate",
    };
    var pre: [16]u8 = undefined;
    var data: [4096]u8 = undefined;
    const pre_len = r.boundaryLen(pre.len);
    const data_len = switch (r.below(8)) {
        0 => 0,
        1 => 1,
        2 => 4096,
        else => r.boundaryLen(data.len),
    };
    randomBytes(r, pre[0..pre_len]);
    randomBytes(r, data[0..data_len]);
    const payload = try proto.packFields(gpa, &.{ mode, pre[0..pre_len], data[0..data_len] });
    return payload;
}

fn genExists(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    const kind = switch (r.below(4)) {
        0 => if (maybeInvalid(r)) "kind-inexistente" else "file",
        1 => "missing",
        2 => "dir",
        else => "file",
    };
    const paths = [_][]const u8{ "x.txt", "sub/y.txt", "dir" };
    const path = r.pick([]const u8, &paths);
    const payload = try proto.packFields(gpa, &.{ kind, path });
    return payload;
}

fn genSplitFmt(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    // separador vacio: invalido (en Python lanza ValueError, en Zig el
    // split por vacio no termina) -> ambos lados deben rechazar el caso.
    const seps = [_][]const u8{ ",", ";", " ", "|", "\t", "" };
    const sep = r.pick([]const u8, &seps);
    var text: [128]u8 = undefined;
    var text_len = r.boundaryLen(text.len);
    if (r.chance(1, 3)) {
        // Trozos con el espacio en blanco de str.isspace() de Python: los
        // bytes aleatorios casi nunca generan \x0b, \x1c-\x1f ni espacios
        // Unicode, y ahi es donde trim(" \t") divergia de str.strip().
        // U+200B (zero width space) y \xff son controles: NO son espacio.
        const pieces = [_][]const u8{
            "a",            "bc",           ",",            ";",            " ",
            "|",            "\t",           "\n",           "\r",           "\x0b",
            "\x0c",         "\x1c",         "\x1f",         "\xc2\x85",     "\xc2\xa0",
            "\xe1\x9a\x80", "\xe2\x80\x83", "\xe2\x80\xa8", "\xe3\x80\x80", "\xe2\x80\x8b",
            "\xff",
        };
        const want = text_len;
        text_len = 0;
        while (true) {
            const piece = r.pick([]const u8, &pieces);
            if (text_len + piece.len > want) break;
            @memcpy(text[text_len..][0..piece.len], piece);
            text_len += piece.len;
        }
    } else {
        randomBytes(r, text[0..text_len]);
    }
    const macs = [_][]const u8{ "aa:bb:cc:dd:ee:ff", "", "corto", "\xc3\xb1mac" };
    const ips = [_][]const u8{ "192.168.1.10", "", "x", "10.0.0.1" };
    const mac = r.pick([]const u8, &macs);
    const ip = r.pick([]const u8, &ips);
    var width_buf: [16]u8 = undefined;
    const width_str: []const u8 = if (maybeInvalid(r))
        "ancho"
    else
        try std.fmt.bufPrint(&width_buf, "{d}", .{r.boundaryLen(24)});
    const payload = try proto.packFields(gpa, &.{ sep, text[0..text_len], mac, ip, width_str });
    return payload;
}

fn genSleep(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    // El esquema duerme de verdad: milisegundos cortos para no gastar el
    // presupuesto del fuzzer en dormir (500 casos por chunk).
    var ms_buf: [16]u8 = undefined;
    const ms_str: []const u8 = if (maybeInvalid(r))
        "-1"
    else
        try std.fmt.bufPrint(&ms_buf, "{d}", .{r.boundaryLen(3)});
    const payload = try proto.packFields(gpa, &.{ms_str});
    return payload;
}

fn genEnv(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    const keys = [_][]const u8{
        "PYZIG_FUZZ_A",
        "PYZIG_FUZZ_B",
        "PATH",
        "HOME",
        "PYZIG_AUSENTE_XYZ",
        "PYZIG_FUZZ_VACIA",
    };
    const key = r.pick([]const u8, &keys);
    const payload = try proto.packFields(gpa, &.{key});
    return payload;
}

fn genSpawn(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var fields: std.ArrayList([]const u8) = .empty;
    defer fields.deinit(gpa);
    var pre: [16]u8 = undefined;
    const pre_len = r.boundaryLen(pre.len);
    randomBytes(r, pre[0..pre_len]);
    try fields.append(gpa, pre[0..pre_len]);
    const tmpl = r.pick([]const []const u8, &COMMANDS);
    for (tmpl) |arg| try fields.append(gpa, arg);
    const payload = try proto.packFields(gpa, fields.items);
    return payload;
}

fn genStdout(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    const stream = if (r.chance(1, 2)) "out" else "err";
    var msg: [256]u8 = undefined;
    const len = r.boundaryLen(msg.len);
    randomBytes(r, msg[0..len]);
    const payload = try proto.packFields(gpa, &.{ stream, msg[0..len] });
    return payload;
}

fn genSha256(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var data: [4096]u8 = undefined;
    const len = switch (r.below(6)) {
        0 => 0,
        1 => 1,
        2 => 4096,
        else => r.boundaryLen(data.len),
    };
    randomBytes(r, data[0..len]);
    const payload = try proto.packFields(gpa, &.{data[0..len]});
    return payload;
}

const B64_NOISE = "\n =!-_*";
const HEX_NOISE = " \n\tgxz0";
const INT_TEXTS = [_][]const u8{
    "0",     "7",    "42",   "-42",          "+5",     "ff",     "FF",
    "0xff",  "0b101", "0o17", "010",          "1_0",    "1__0",   "_1",
    " 7 ",   "7\n",  "",     "2147483647",   "2147483648", "-2147483648",
    "-2147483649", "zz", "12a", "101", "99999999999999999999", "-", "0",
};
const INT_BASES = [_][]const u8{ "0", "2", "8", "10", "16", "36", "1", "37", "x" };

/// Copia `src` a `out` aplicando una mutacion elegida por el stream: intacto,
/// truncado, insercion, sustitucion o ruido de longitud acotada.
fn mutate(r: *Rng, src: []const u8, out: []u8, noise: []const u8) []u8 {
    @memcpy(out[0..src.len], src);
    var n = src.len;
    switch (r.below(5)) {
        0 => {},
        1 => {
            if (n > 0) n -= 1;
        },
        2 => {
            const pos = r.below(n + 1);
            std.mem.copyBackwards(u8, out[pos + 1 .. n + 1], out[pos..n]);
            out[pos] = r.pick(u8, noise);
            n += 1;
        },
        3 => {
            if (n > 0) out[r.below(n)] = r.pick(u8, noise);
        },
        else => {
            n = r.boundaryLen(out.len);
            r.ascii(out[0..n], noise);
        },
    }
    return out[0..n];
}

/// base64/v1: codificar bytes aleatorios, o decodificar texto valido mutado
/// (relleno, caracteres fuera del alfabeto, saltos de linea, longitud).
fn genBase64(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var data: [192]u8 = undefined;
    const len = r.boundaryLen(data.len);
    r.fill(data[0..len]);
    const enc_op: []const u8 = "enc";
    const dec_op: []const u8 = "dec";
    if (r.chance(1, 2)) return proto.packFields(gpa, &.{ enc_op, data[0..len] });
    var valid: [256]u8 = undefined;
    const n = std.base64.standard.Encoder.calcSize(len);
    _ = std.base64.standard.Encoder.encode(valid[0..n], data[0..len]);
    var out: [320]u8 = undefined;
    const text = mutate(r, valid[0..n], &out, B64_NOISE);
    return proto.packFields(gpa, &.{ dec_op, text });
}

/// hex/v1: bytes -> hex (minusculas o mayusculas) y hex -> bytes, con pares
/// separados por espacios (Python los ignora, hexToBytes no) y mutaciones.
fn genHex(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var data: [128]u8 = undefined;
    const len = r.boundaryLen(data.len);
    r.fill(data[0..len]);
    const enc_op: []const u8 = "enc";
    const dec_op: []const u8 = "dec";
    if (r.chance(1, 2)) return proto.packFields(gpa, &.{ enc_op, data[0..len] });
    const digits: []const u8 = if (r.chance(1, 2)) "0123456789abcdef" else "0123456789ABCDEF";
    var pairs: [256]u8 = undefined;
    for (data[0..len], 0..) |b, i| {
        pairs[2 * i] = digits[b >> 4];
        pairs[2 * i + 1] = digits[b & 0x0f];
    }
    var spaced: [384]u8 = undefined;
    var src: []const u8 = pairs[0 .. 2 * len];
    if (r.chance(1, 4)) {
        var k: usize = 0;
        var i: usize = 0;
        while (i < len) : (i += 1) {
            spaced[k] = pairs[2 * i];
            spaced[k + 1] = pairs[2 * i + 1];
            k += 2;
            if (i + 1 < len) {
                spaced[k] = ' ';
                k += 1;
            }
        }
        src = spaced[0..k];
    }
    var out: [400]u8 = undefined;
    const text = mutate(r, src, &out, HEX_NOISE);
    return proto.packFields(gpa, &.{ dec_op, text });
}

/// parseint/v1: texto (literales conocidos o ruido) y base (0, 2..36, o invalida).
fn genParseInt(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var buf: [24]u8 = undefined;
    const text: []const u8 = if (r.chance(1, 3)) blk: {
        const n = r.boundaryLen(buf.len);
        r.ascii(buf[0..n], "0123456789abcdefxyzXYZ+-_ ");
        break :blk buf[0..n];
    } else r.pick([]const u8, &INT_TEXTS);
    const base = r.pick([]const u8, &INT_BASES);
    return proto.packFields(gpa, &.{ text, base });
}

// --- mate_bytes: enteros con borde (0, +-1, extremos, divisor 0) -------------
// Formato estricto `-?[0-9]+` en ambos lados; lo demas es invalid.

const DIV_EDGES = [_][]const u8{
    "0",          "1",         "-1",         "2",          "-2",
    "3",          "-3",        "7",          "-7",         "8",
    "-8",         "65536",     "-65536",     "2147483646", "2147483647",
    "-2147483647", "-2147483648",
};
const BIT_EDGES = [_][]const u8{
    "0",                    "1",                  "-1",                  "2",
    "-2",                   "255",                "-255",                "256",
    "65535",                "65536",              "4294967295",          "4294967296",
    "-4294967296",          "4611686018427387904", "9223372036854775807", "-9223372036854775807",
    "-9223372036854775808",
};
/// Texto que los esquemas numericos rechazan (vacio, signos sueltos, decimales,
/// espacios, prefijos, fuera de rango). Algunos son validos en i64 (2147483648):
/// ambos lados deciden igual, asi que el caso sigue siendo una comparacion.
const NUM_INVALID = [_][]const u8{
    "",   "x",  "-",   "+5",  "1.5",  " 7",  "7 ",   "0x10", "1_000", "--7",
    "2147483648", "-2147483649", "9223372036854775808", "99999999999999999999",
};
const PACK_OPS = [_][]const u8{ "pack", "read", "readi", "write" };
const ENDIANS = [_][]const u8{ "big", "little" };
const PACK_VALUES = [_][]const u8{
    "0",          "1",          "255",        "256",        "65535",
    "65536",      "2147483647", "2147483648", "4294967295", "4294967296",
    "-1",         "-2147483648",
};
const PACK_OFFSETS = [_][]const u8{ "0", "1", "2", "3", "4", "5", "8", "12", "13" };

/// Entero i32 decimal: borde, aleatorio uniforme o texto invalido.
fn i32Text(r: *Rng, buf: []u8) []const u8 {
    if (maybeInvalid(r)) return r.pick([]const u8, &NUM_INVALID);
    if (r.chance(1, 2)) return r.pick([]const u8, &DIV_EDGES);
    return std.fmt.bufPrint(buf, "{d}", .{r.random().int(i32)}) catch unreachable;
}

/// divmod/v1: a y b. El divisor 0 tiene peso propio: es el error de la receta.
fn genDivMod(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var a_buf: [16]u8 = undefined;
    var b_buf: [16]u8 = undefined;
    const a: []const u8 = i32Text(r, &a_buf);
    const b: []const u8 = if (r.chance(1, 6)) "0" else i32Text(r, &b_buf);
    return proto.packFields(gpa, &.{ a, b });
}

/// bits/v1: count (bit_count con signo) o length (bit_length), i64 decimal.
fn genBits(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var buf: [24]u8 = undefined;
    const op: []const u8 = if (maybeInvalid(r)) "popcount" else if (r.chance(1, 2)) "count" else "length";
    const text: []const u8 = if (maybeInvalid(r))
        r.pick([]const u8, &NUM_INVALID)
    else if (r.chance(1, 2))
        r.pick([]const u8, &BIT_EDGES)
    else
        try std.fmt.bufPrint(&buf, "{d}", .{r.random().int(i64)});
    return proto.packFields(gpa, &.{ op, text });
}

/// packint/v1: pack/read/readi/write de un u32/i32 con endian, en un offset.
fn genPackInt(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var vbuf: [16]u8 = undefined;
    const op: []const u8 = if (maybeInvalid(r)) "unpack" else r.pick([]const u8, &PACK_OPS);
    const endian: []const u8 = if (maybeInvalid(r)) "middle" else r.pick([]const u8, &ENDIANS);
    const value: []const u8 = if (maybeInvalid(r))
        r.pick([]const u8, &NUM_INVALID)
    else if (r.chance(1, 2))
        r.pick([]const u8, &PACK_VALUES)
    else
        try std.fmt.bufPrint(&vbuf, "{d}", .{r.random().int(u32)});
    const offset: []const u8 = if (maybeInvalid(r))
        (if (r.chance(1, 2)) "-1" else r.pick([]const u8, &NUM_INVALID))
    else
        r.pick([]const u8, &PACK_OFFSETS);
    var data: [12]u8 = undefined;
    const len = r.boundaryLen(data.len);
    r.fill(data[0..len]);
    return proto.packFields(gpa, &.{ op, endian, value, offset, data[0..len] });
}

fn genPipe(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var data: [4096]u8 = undefined;
    const len = switch (r.below(6)) {
        0 => 0,
        1 => 1,
        2 => 4096,
        else => r.boundaryLen(data.len),
    };
    randomBytes(r, data[0..len]);
    const payload = try proto.packFields(gpa, &.{data[0..len]});
    return payload;
}

/// Build one case payload for a schema.
pub fn generate(gpa: std.mem.Allocator, schema: Schema, r: *Rng) ![]u8 {
    return switch (schema) {
        .argv => genArgv(r, gpa),
        .kv => genKv(r, gpa),
        .read => genRead(r, gpa),
        .write => genWrite(r, gpa),
        .exists => genExists(r, gpa),
        .splitfmt => genSplitFmt(r, gpa),
        .sleep => genSleep(r, gpa),
        .env => genEnv(r, gpa),
        .spawn => genSpawn(r, gpa),
        .stdout => genStdout(r, gpa),
        .sha256 => genSha256(r, gpa),
        .base64 => genBase64(r, gpa),
        .hex => genHex(r, gpa),
        .parseint => genParseInt(r, gpa),
        .divmod => genDivMod(r, gpa),
        .bits => genBits(r, gpa),
        .packint => genPackInt(r, gpa),
        .pipe => genPipe(r, gpa),
    };
}

test "generation is deterministic for a seed" {
    const gpa = std.testing.allocator;
    var a = Rng.init(99);
    var b = Rng.init(99);
    inline for (@typeInfo(Schema).@"enum".fields) |f| {
        const schema: Schema = @enumFromInt(f.value);
        const pa = try generate(gpa, schema, &a);
        defer gpa.free(pa);
        const pb = try generate(gpa, schema, &b);
        defer gpa.free(pb);
        try std.testing.expectEqualSlices(u8, pa, pb);
    }
}

test "argv cases always carry a program name" {
    const gpa = std.testing.allocator;
    var r = Rng.init(3);
    var i: usize = 0;
    while (i < 50) : (i += 1) {
        const payload = try generate(gpa, .argv, &r);
        defer gpa.free(payload);
        var f = proto.Fields.init(payload);
        const first = f.next().?;
        try std.testing.expect(first.len > 0);
    }
}

test "read cases keep limit and content consistent" {
    const gpa = std.testing.allocator;
    var r = Rng.init(11);
    const payload = try generate(gpa, .read, &r);
    defer gpa.free(payload);
    var f = proto.Fields.init(payload);
    const path = f.next().?;
    const present = f.next().?;
    _ = f.next().?;
    const limit = f.next().?;
    try std.testing.expect(path.len > 0);
    try std.testing.expect(present.len == 1);
    try std.testing.expect(limit.len > 0);
}

test "every schema produces a decodable case" {
    const gpa = std.testing.allocator;
    inline for (@typeInfo(Schema).@"enum".fields) |f| {
        const schema: Schema = @enumFromInt(f.value);
        var r = Rng.init(7);
        var i: usize = 0;
        while (i < 20) : (i += 1) {
            const payload = try generate(gpa, schema, &r);
            defer gpa.free(payload);
            var fields = proto.Fields.init(payload);
            var count: usize = 0;
            while (fields.next() != null) count += 1;
            try std.testing.expect(count >= 1);
        }
    }
}
