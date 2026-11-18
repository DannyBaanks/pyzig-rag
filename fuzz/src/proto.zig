// Wire protocol between the Zig fuzzer, the Zig subject drivers and the
// Python oracle.
//
// Cases and observations are binary-safe: a payload is a sequence of
// length-prefixed fields (u32 little endian length + payload bytes). No
// separator can ever collide with user data, so NUL bytes, newlines and
// invalid UTF-8 survive a round trip untouched.
//
// On disk one case/observation is one line:
//   cases:      <hex payload>
//   observation: <status>\t<hex payload>
const std = @import("std");

pub const Status = enum {
    ok,
    err,
    /// El caso no es aplicable a este lado (la operacion no existe aqui).
    unsupported,
    /// El caso es invalido para este lado (entrada malformada).
    invalid,
    crash,
    timeout,
    missing,

    pub fn name(self: Status) []const u8 {
        return switch (self) {
            .ok => "ok",
            .err => "err",
            .unsupported => "unsupported",
            .invalid => "invalid",
            .crash => "crash",
            .timeout => "timeout",
            .missing => "missing",
        };
    }

    pub fn fromName(s: []const u8) ?Status {
        inline for (@typeInfo(Status).@"enum".fields) |f| {
            if (std.mem.eql(u8, s, f.name)) return @enumFromInt(f.value);
        }
        return null;
    }
};

/// Encode fields as: u32le length + bytes, repeated.
pub fn packFields(gpa: std.mem.Allocator, fields: []const []const u8) ![]u8 {
    var total: usize = 0;
    for (fields) |f| total += 4 + f.len;
    var out = try gpa.alloc(u8, total);
    errdefer gpa.free(out);
    var pos: usize = 0;
    for (fields) |f| {
        std.mem.writeInt(u32, out[pos..][0..4], @intCast(f.len), .little);
        pos += 4;
        @memcpy(out[pos..][0..f.len], f);
        pos += f.len;
    }
    return out;
}

/// Sequential reader over a packed field sequence.
pub const Fields = struct {
    buf: []const u8,
    pos: usize = 0,

    pub fn init(buf: []const u8) Fields {
        return .{ .buf = buf };
    }

    pub fn next(self: *Fields) ?[]const u8 {
        if (self.pos + 4 > self.buf.len) return null;
        const len = std.mem.readInt(u32, self.buf[self.pos..][0..4], .little);
        self.pos += 4;
        if (self.pos + len > self.buf.len) return null;
        const f = self.buf[self.pos .. self.pos + len];
        self.pos += len;
        return f;
    }

    pub fn rest(self: *const Fields) []const u8 {
        return self.buf[self.pos..];
    }
};

pub fn hexEncode(gpa: std.mem.Allocator, bytes: []const u8) ![]u8 {
    const digits = "0123456789abcdef";
    const out = try gpa.alloc(u8, bytes.len * 2);
    for (bytes, 0..) |b, i| {
        out[2 * i] = digits[b >> 4];
        out[2 * i + 1] = digits[b & 0x0f];
    }
    return out;
}

pub fn hexDecode(gpa: std.mem.Allocator, hex: []const u8) ![]u8 {
    if (hex.len % 2 != 0) return error.BadHex;
    const out = try gpa.alloc(u8, hex.len / 2);
    errdefer gpa.free(out);
    _ = std.fmt.hexToBytes(out, hex) catch return error.BadHex;
    return out;
}

/// One observation: status plus the packed field payload.
pub const Obs = struct {
    status: Status,
    payload: []const u8,
    fields: Fields,

    pub fn field(self: *const Obs, i: usize) ?[]const u8 {
        var f = self.fields;
        var n: usize = 0;
        while (f.next()) |item| {
            if (n == i) return item;
            n += 1;
        }
        return null;
    }
};

/// Serialize an observation as one protocol line (without the trailing \n).
pub fn encodeObsLine(gpa: std.mem.Allocator, status: Status, fields: []const []const u8) ![]u8 {
    const payload = try packFields(gpa, fields);
    defer gpa.free(payload);
    const hex = try hexEncode(gpa, payload);
    defer gpa.free(hex);
    return std.fmt.allocPrint(gpa, "{s}\t{s}", .{ status.name(), hex });
}

pub fn parseObsLine(gpa: std.mem.Allocator, line: []const u8) !Obs {
    const tab = std.mem.indexOfScalar(u8, line, '\t') orelse return error.BadObsLine;
    const status = Status.fromName(line[0..tab]) orelse return error.BadObsLine;
    const payload = try hexDecode(gpa, line[tab + 1 ..]);
    return .{ .status = status, .payload = payload, .fields = Fields.init(payload) };
}

pub fn freeObs(gpa: std.mem.Allocator, obs: Obs) void {
    gpa.free(obs.payload);
}

/// Split a buffer into lines without the trailing newline; empty lines are
/// skipped (they carry no case).
pub fn splitLines(buf: []const u8, gpa: std.mem.Allocator) ![][]const u8 {
    var out: std.ArrayList([]const u8) = .empty;
    errdefer out.deinit(gpa);
    var it = std.mem.splitScalar(u8, buf, '\n');
    while (it.next()) |line| {
        if (line.len == 0) continue;
        try out.append(gpa, line);
    }
    return out.toOwnedSlice(gpa);
}

test "fields round trip with binary payloads" {
    const gpa = std.testing.allocator;
    const weird = [_][]const u8{ "a", "", "\x00\n\r", "\xff\xfe" };
    const blob = try packFields(gpa, &weird);
    defer gpa.free(blob);
    var f = Fields.init(blob);
    try std.testing.expectEqualStrings("a", f.next().?);
    try std.testing.expectEqualStrings("", f.next().?);
    try std.testing.expectEqualStrings("\x00\n\r", f.next().?);
    try std.testing.expectEqualStrings("\xff\xfe", f.next().?);
    try std.testing.expect(f.next() == null);
}

test "observation line round trip" {
    const gpa = std.testing.allocator;
    const line = try encodeObsLine(gpa, .err, &.{"FileNotFound"});
    defer gpa.free(line);
    var obs = try parseObsLine(gpa, line);
    defer freeObs(gpa, obs);
    try std.testing.expectEqual(Status.err, obs.status);
    try std.testing.expectEqualStrings("FileNotFound", obs.field(0).?);
}

test "hex round trip" {
    const gpa = std.testing.allocator;
    const raw = [_]u8{ 0x00, 0x0a, 0x7f, 0xff };
    const hex = try hexEncode(gpa, &raw);
    defer gpa.free(hex);
    try std.testing.expectEqualStrings("000a7fff", hex);
    const back = try hexDecode(gpa, hex);
    defer gpa.free(back);
    try std.testing.expectEqualSlices(u8, &raw, back);
}
