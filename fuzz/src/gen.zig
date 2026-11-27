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
//   packint/v1     [op, endian, value, offset, data]   op: pack | read | readi | write
//   straffix/v1    [op, s, a, b]                       op: starts | ends | find | replace
//   parsefloat/v1  [op, text]                          op: parse | fmt2
//   sortkey/v1     [op, rev, item...]                  op: byage | strings
//   intbytes/v1    [op, width, signed, endian, value, data]
//   roundfloat/v1  [op, hex_bits]                      op: round_even | floor | ceil | zig_round
//   utf8cp/v1      [data]                              bytes arbitrarios (UTF-8 valido o invalido)
//   pipe/v1        [data]                              (reservado para pipelines, F2)
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
    straffix,
    parsefloat,
    sortkey,
    intbytes,
    roundfloat,
    utf8cp,
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

// --- ola 6: straffix, parsefloat, sortkey, intbytes, roundfloat, utf8cp -----

const AFFIX_OPS = [_][]const u8{ "starts", "ends", "find", "replace" };
const UTF8_PIECES = [_][]const u8{
    "a", "b", "aa", "foo", "bar", ".", "-", " ",
    "\xc3\xa9", "\xc3\xb1", "\xe2\x82\xac", "\xf0\x9f\x98\x80",
};

fn buildUtf8(r: *Rng, buf: []u8, max_pieces: usize) []u8 {
    const n_pieces = r.boundaryLen(max_pieces);
    var pos: usize = 0;
    var i: usize = 0;
    while (i < n_pieces) : (i += 1) {
        const piece = r.pick([]const u8, &UTF8_PIECES);
        if (pos + piece.len > buf.len) break;
        @memcpy(buf[pos..][0..piece.len], piece);
        pos += piece.len;
    }
    return buf[0..pos];
}

fn genStrAffix(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    const op: []const u8 = if (maybeInvalid(r)) "split" else r.pick([]const u8, &AFFIX_OPS);
    var sbuf: [64]u8 = undefined;
    var abuf: [24]u8 = undefined;
    var bbuf: [24]u8 = undefined;
    var s: []const u8 = buildUtf8(r, &sbuf, 8);
    var a: []const u8 = if (r.chance(1, 5)) "" else buildUtf8(r, &abuf, 3);
    const b: []const u8 = if (r.chance(1, 4)) "" else buildUtf8(r, &bbuf, 3);
    // sesgar para que `a` aparezca como prefijo, sufijo o subcadena de `s`
    if (s.len > 0 and r.chance(1, 3)) {
        switch (r.below(3)) {
            0 => {
                // prefijo en limite de codepoint
                var k = r.below(s.len + 1);
                while (k < s.len and (s[k] & 0xc0) == 0x80) k += 1;
                a = s[0..k];
            },
            1 => {
                // sufijo en limite de codepoint
                var k = r.below(s.len + 1);
                while (k < s.len and (s[k] & 0xc0) == 0x80) k += 1;
                a = s[k..];
            },
            else => {
                var lo = r.below(s.len);
                while (lo < s.len and (s[lo] & 0xc0) == 0x80) lo += 1;
                var hi = lo + r.below(s.len - lo + 1);
                while (hi < s.len and (s[hi] & 0xc0) == 0x80) hi += 1;
                a = s[lo..hi];
            },
        }
    }
    if (maybeInvalid(r)) s = "\xff\xfe";
    return proto.packFields(gpa, &.{ op, s, a, b });
}

const FLOAT_TEXTS = [_][]const u8{
    "0",          "-0",       "0.0",        "-0.0",        "3.14",
    "-1.5e3",     "+2",       ".5",         "5.",          "1e-10",
    "1e309",      "-1e309",   "1e-325",     "inf",         "-inf",
    "+inf",       "Infinity", "nan",        "-nan",        "NaN",
    "1_000.5",    "1__0.5",   " 1.5 ",      "1.5\n",       "0x1p3",
    "0x1.8p+1",   "",         "1,5",        "abc",         "1.5x",
    ".",          "+",        "-",          "e10",         "1e",
    "2.675",      "0.125",    "2.5",        "-2.5",        "1234.567",
};

const FLOAT_EDGE_BITS = [_]u64{
    @bitCast(@as(f64, 0.0)),
    @bitCast(@as(f64, -0.0)),
    @bitCast(@as(f64, 0.5)),
    @bitCast(@as(f64, -0.5)),
    @bitCast(@as(f64, 1.5)),
    @bitCast(@as(f64, -1.5)),
    @bitCast(@as(f64, 2.5)),
    @bitCast(@as(f64, -2.5)),
    @bitCast(@as(f64, 3.5)),
    @bitCast(@as(f64, -3.5)),
    @bitCast(@as(f64, 2.675)),
    @bitCast(@as(f64, 0.125)),
    @bitCast(@as(f64, 2.4)),
    @bitCast(@as(f64, -2.4)),
    @bitCast(@as(f64, 2.6)),
    @bitCast(@as(f64, 3.14159)),
    @bitCast(@as(f64, 1234.567)),
    @bitCast(@as(f64, 0.49999999999999994)), // 0.5 - 1 ulp
    @bitCast(@as(f64, -0.49999999999999994)),
    @bitCast(@as(f64, 0.5000000000000001)),  // 0.5 + 1 ulp
    @bitCast(@as(f64, -0.5000000000000001)),
    @bitCast(@as(f64, -0.49999999999999997)), // -(0.5 - 2^-54): diff == 0.5 al redondear!
    @bitCast(@as(f64, 4503599627370495.5)),   // 2^52 - 0.5
    @bitCast(@as(f64, -4503599627370495.5)),
    @bitCast(@as(f64, 4503599627370496.0)),   // 2^52
    @bitCast(@as(f64, 1e20)),
    @bitCast(@as(f64, -1e20)),
    @bitCast(@as(f64, 1e-308)),
    0x0000000000000001, // subnormal minimo positivo
    0x8000000000000001, // subnormal minimo negativo
    @bitCast(std.math.inf(f64)),
    @bitCast(-std.math.inf(f64)),
    @bitCast(std.math.nan(f64)),
};

fn randomFiniteF64Bits(r: *Rng) u64 {
    // floats moderados [-1e6, 1e6] mas potencias de 2 y medios enteros
    switch (r.below(4)) {
        0 => {
            const k: f64 = @floatFromInt(r.random().intRangeAtMost(i32, -1000, 1000));
            return @bitCast(k + 0.5);
        },
        1 => {
            const raw: f64 = @floatFromInt(r.random().intRangeAtMost(i32, -100000, 100000));
            return @bitCast(raw / 1000.0);
        },
        2 => {
            const exp: u64 = r.random().intRangeAtMost(u64, 990, 1075);
            const sign: u64 = @as(u64, @intFromBool(r.chance(1, 2))) << 63;
            const mant: u64 = r.random().int(u64) & ((@as(u64, 1) << 52) - 1);
            return sign | (exp << 52) | mant;
        },
        else => return r.pick(u64, &FLOAT_EDGE_BITS),
    }
}

fn genParseFloat(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    const op: []const u8 = if (maybeInvalid(r)) "fmt3" else if (r.chance(1, 2)) "parse" else "fmt2";
    if (std.mem.eql(u8, op, "parse")) {
        var buf: [24]u8 = undefined;
        const text: []const u8 = if (r.chance(1, 3)) blk: {
            const n = r.boundaryLen(buf.len);
            r.ascii(buf[0..n], "0123456789.eE+-_ infanxXp,");
            break :blk buf[0..n];
        } else r.pick([]const u8, &FLOAT_TEXTS);
        return proto.packFields(gpa, &.{ op, text });
    }
    var hbuf: [16]u8 = undefined;
    const text: []const u8 = if (maybeInvalid(r))
        "zzzz"
    else
        try std.fmt.bufPrint(&hbuf, "{x:0>16}", .{randomFiniteF64Bits(r)});
    return proto.packFields(gpa, &.{ op, text });
}

const SORT_NAMES = [_][]const u8{
    "a", "b", "c", "d", "e", "ana", "bob", "cy", "x1", "z9", "", "\xc3\xa9",
};
const SORT_AGES = [_][]const u8{
    "0", "1", "2", "3", "4", "5", "20", "30", "4294967295",
};
const SORT_STRS = [_][]const u8{
    "", "a", "aa", "ab", "b", "A", "Zeta", "ave", "manzana", "pera",
    "\xc3\xa9", "\xc3\xb1", "\xe2\x82\xac", "\xf0\x9f\x98\x80", "a\xc3\xa9",
};

fn genSortKey(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var fields: std.ArrayList([]const u8) = .empty;
    defer fields.deinit(gpa);
    const op: []const u8 = if (maybeInvalid(r)) "rsort" else if (r.chance(2, 3)) "byage" else "strings";
    try fields.append(gpa, op);
    if (std.mem.eql(u8, op, "byage")) {
        const rev: []const u8 = if (maybeInvalid(r)) "2" else if (r.chance(1, 2)) "1" else "0";
        try fields.append(gpa, rev);
        const count = r.boundaryLen(16);
        var i: usize = 0;
        while (i < count) : (i += 1) {
            try fields.append(gpa, r.pick([]const u8, &SORT_NAMES));
            const age = if (maybeInvalid(r)) "-1" else r.pick([]const u8, &SORT_AGES);
            try fields.append(gpa, age);
        }
    } else {
        const rev: []const u8 = if (maybeInvalid(r)) "1" else "0";
        try fields.append(gpa, rev);
        const count = r.boundaryLen(16);
        var i: usize = 0;
        while (i < count) : (i += 1) {
            if (maybeInvalid(r)) {
                try fields.append(gpa, "\xff");
            } else {
                try fields.append(gpa, r.pick([]const u8, &SORT_STRS));
            }
        }
    }
    return proto.packFields(gpa, fields.items);
}

const INTBYTES_WIDTHS = [_][]const u8{ "1", "4", "8" };
const INTBYTES_VALUES = [_][]const u8{
    "0", "1", "-1", "127", "128", "-128", "-129", "255", "256", "300",
    "16909060", "-2", "2147483647", "2147483648", "-2147483648", "-2147483649",
    "4294967295", "4294967296", "9223372036854775807", "9223372036854775808",
    "-9223372036854775808", "-9223372036854775809",
    "18446744073709551615", "18446744073709551616",
};

fn genIntBytes(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var vbuf: [40]u8 = undefined;
    const op: []const u8 = if (maybeInvalid(r)) "cast" else if (r.chance(1, 2)) "to" else "from";
    const width_s: []const u8 = if (maybeInvalid(r)) "3" else r.pick([]const u8, &INTBYTES_WIDTHS);
    const signed_s: []const u8 = if (maybeInvalid(r)) "2" else if (r.chance(1, 2)) "1" else "0";
    const endian: []const u8 = if (maybeInvalid(r)) "native" else r.pick([]const u8, &ENDIANS);
    const val: []const u8 = if (maybeInvalid(r))
        r.pick([]const u8, &NUM_INVALID)
    else if (r.chance(2, 3))
        r.pick([]const u8, &INTBYTES_VALUES)
    else
        try std.fmt.bufPrint(&vbuf, "{d}", .{r.random().int(i64)});
    var data: [8]u8 = undefined;
    const wlen: usize = if (std.mem.eql(u8, width_s, "1"))
        1
    else if (std.mem.eql(u8, width_s, "4"))
        4
    else if (std.mem.eql(u8, width_s, "8"))
        8
    else
        2;
    const dlen: usize = if (maybeInvalid(r)) r.below(8) else wlen;
    r.fill(data[0..dlen]);
    return proto.packFields(gpa, &.{ op, width_s, signed_s, endian, val, data[0..dlen] });
}

const ROUND_OPS = [_][]const u8{ "round_even", "floor", "ceil", "zig_round" };

fn genRoundFloat(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    const op: []const u8 = if (maybeInvalid(r)) "trunc" else r.pick([]const u8, &ROUND_OPS);
    var hbuf: [16]u8 = undefined;
    const hex_bits: []const u8 = if (maybeInvalid(r))
        "0123"
    else
        try std.fmt.bufPrint(&hbuf, "{x:0>16}", .{randomFiniteF64Bits(r)});
    return proto.packFields(gpa, &.{ op, hex_bits });
}

const UTF8_VALID = [_][]const u8{
    "", "a", "abc", "\x00", "a\xc3\xa9\xe2\x82\xac", "\xf0\x9f\x98\x80",
    "\xc2\x80", "\xdf\xbf", "\xe0\xa0\x80", "\xed\x9f\xbf", "\xee\x80\x80",
    "\xef\xbf\xbf", "\xf0\x90\x80\x80", "\xf4\x8f\xbf\xbf",
};
const UTF8_INVALID = [_][]const u8{
    "\x80", "\xbf", "\xc0\x80", "\xc1\xbf", "\xe0\x80\x80", "\xed\xa0\x80",
    "\xed\xbf\xbf", "\xf0\x80\x80\x80", "\xf4\x90\x80\x80", "\xf5\x80\x80\x80",
    "\xfe", "\xff", "\xc3", "\xe2\x82", "\xf0\x9f\x98",
};

fn genUtf8Cp(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(gpa);
    switch (r.below(4)) {
        0 => {
            const n = r.boundaryLen(8);
            var i: usize = 0;
            while (i < n) : (i += 1) {
                try out.appendSlice(gpa, r.pick([]const u8, &UTF8_VALID));
            }
        },
        1 => {
            const n = r.boundaryLen(4);
            var i: usize = 0;
            while (i < n) : (i += 1) {
                try out.appendSlice(gpa, r.pick([]const u8, &UTF8_VALID));
            }
            try out.appendSlice(gpa, r.pick([]const u8, &UTF8_INVALID));
            if (r.chance(1, 2)) try out.appendSlice(gpa, r.pick([]const u8, &UTF8_VALID));
        },
        2 => {
            try out.appendSlice(gpa, r.pick([]const u8, &UTF8_INVALID));
        },
        else => {
            var buf: [32]u8 = undefined;
            const n = r.boundaryLen(buf.len);
            r.fill(buf[0..n]);
            try out.appendSlice(gpa, buf[0..n]);
        },
    }
    return proto.packFields(gpa, &.{out.items});
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
        .straffix => genStrAffix(r, gpa),
        .parsefloat => genParseFloat(r, gpa),
        .sortkey => genSortKey(r, gpa),
        .intbytes => genIntBytes(r, gpa),
        .roundfloat => genRoundFloat(r, gpa),
        .utf8cp => genUtf8Cp(r, gpa),
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
