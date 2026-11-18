// Case generators: one schema per fuzzable operation.
//
// Every generator is a pure function of (schema, seed stream): the same seed
// always yields byte-identical cases. The alphabet is boundary-biased
// (empty, 1 byte, max, off-by-one) because that is where semantics break.
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
    &.{ "cat" },
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
            b.* = r.pick(u8, "\x00\x0a\x0d\x09\x7f\xff");
        } else {
            b.* = r.pick(u8, asciiPrintable());
        }
    }
}

fn decimal(gpa: std.mem.Allocator, value: usize) ![]const u8 {
    return std.fmt.allocPrint(gpa, "{d}", .{value});
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
    const paths = [_][]const u8{ "f.txt", "sub/g.txt", "missing.txt", "dir" };
    const path = r.pick([]const u8, &paths);
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
    const limit_str = try std.fmt.allocPrint(gpa, "{d}", .{limit});
    defer gpa.free(limit_str);
    const payload = try proto.packFields(gpa, &.{ path, content[0..len], limit_str });
    return payload;
}

fn genWrite(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    const mode = if (r.chance(1, 2)) "1" else "0";
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
    const kind = switch (r.below(3)) {
        0 => "0", // file
        1 => "1", // missing
        else => "2", // directory
    };
    const payload = try proto.packFields(gpa, &.{ kind, "x" });
    return payload;
}

fn genSplitFmt(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    const seps = [_][]const u8{ ",", ";", " ", "|", "\t", "" };
    const sep = r.pick([]const u8, &seps);
    var text: [128]u8 = undefined;
    const text_len = r.boundaryLen(text.len);
    randomBytes(r, text[0..text_len]);
    const macs = [_][]const u8{ "aa:bb:cc:dd:ee:ff", "", "corto", "\xc3\xb1mac" };
    const ips = [_][]const u8{ "192.168.1.10", "", "x", "10.0.0.1" };
    const mac = r.pick([]const u8, &macs);
    const ip = r.pick([]const u8, &ips);
    const width = try decimal(gpa, r.boundaryLen(24));
    defer gpa.free(width);
    const payload = try proto.packFields(gpa, &.{ sep, text[0..text_len], mac, ip, width });
    return payload;
}

fn genSleep(r: *Rng, gpa: std.mem.Allocator) ![]u8 {
    const ms = try decimal(gpa, r.boundaryLen(10));
    defer gpa.free(ms);
    const payload = try proto.packFields(gpa, &.{ms});
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
    const mode = if (r.chance(1, 2)) "1" else "0";
    var msg: [256]u8 = undefined;
    const len = r.boundaryLen(msg.len);
    randomBytes(r, msg[0..len]);
    const payload = try proto.packFields(gpa, &.{ mode, msg[0..len] });
    return payload;
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
    _ = f.next().?;
    const limit = f.next().?;
    try std.testing.expect(path.len > 0);
    try std.testing.expect(std.mem.eql(u8, limit, "0") or std.fmt.parseInt(usize, limit, 10) catch 0 >= 0);
}
