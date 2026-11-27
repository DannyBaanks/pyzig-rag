// Driver: intbytes/v1 — corpus recipe zig0.16/int-from-bytes-to-bytes-endian
//
// Case:    [op, width, signed, endian, value, data]
//          op:     to | from
//          width:  1 | 4 | 8
//          signed: 0 | 1
//          endian: big | little
//          value:  entero i128 decimal estricto (-?[0-9]+) (usado en `to`)
//          data:   bytes crudos de longitud == width (usado en `from`)
// Fields:  status, error, value, out
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn parseI128Strict(text: []const u8) ?i128 {
    var s = text;
    if (s.len > 0 and s[0] == '-') s = s[1..];
    if (s.len == 0) return null;
    for (s) |c| if (c < '0' or c > '9') return null;
    return std.fmt.parseInt(i128, text, 10) catch null;
}

fn doTo(comptime T: type, gpa: std.mem.Allocator, value: i128, endian: std.builtin.Endian, obs: *std.ArrayList(u8)) !void {
    const lo: i128 = std.math.minInt(T);
    const hi: i128 = std.math.maxInt(T);
    if (value < lo or value > hi) {
        return lib.appendObs(gpa, obs, "err", &.{ "err", "OutOfRange", "", "" });
    }
    var out: [@sizeOf(T)]u8 = undefined;
    toBytes(T, @intCast(value), endian, &out);
    const hex = try lib.hexEncode(gpa, &out);
    defer gpa.free(hex);
    return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", "", hex });
}

fn doFrom(comptime T: type, gpa: std.mem.Allocator, data: []const u8, endian: std.builtin.Endian, obs: *std.ArrayList(u8)) !void {
    if (data.len != @sizeOf(T)) return lib.invalid(gpa, obs, 4);
    const ptr: *const [@sizeOf(T)]u8 = data[0..@sizeOf(T)];
    const v = fromBytes(T, ptr, endian);
    var buf: [32]u8 = undefined;
    const s = try std.fmt.bufPrint(&buf, "{d}", .{v});
    return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", s, "" });
}

fn handle(gpa: std.mem.Allocator, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 6) return lib.invalid(gpa, obs, 4);
    const op = fields[0];
    const width_s = fields[1];
    const signed_s = fields[2];
    const endian: std.builtin.Endian = if (std.mem.eql(u8, fields[3], "big"))
        .big
    else if (std.mem.eql(u8, fields[3], "little"))
        .little
    else
        return lib.invalid(gpa, obs, 4);

    const width: usize = if (std.mem.eql(u8, width_s, "1"))
        1
    else if (std.mem.eql(u8, width_s, "4"))
        4
    else if (std.mem.eql(u8, width_s, "8"))
        8
    else
        return lib.invalid(gpa, obs, 4);

    const signed: bool = if (std.mem.eql(u8, signed_s, "0"))
        false
    else if (std.mem.eql(u8, signed_s, "1"))
        true
    else
        return lib.invalid(gpa, obs, 4);

    const is_to = std.mem.eql(u8, op, "to");
    const is_from = std.mem.eql(u8, op, "from");
    if (!(is_to or is_from)) return lib.invalid(gpa, obs, 4);

    if (is_to) {
        const value = parseI128Strict(fields[4]) orelse return lib.invalid(gpa, obs, 4);
        return switch (width) {
            1 => if (signed) doTo(i8, gpa, value, endian, obs) else doTo(u8, gpa, value, endian, obs),
            4 => if (signed) doTo(i32, gpa, value, endian, obs) else doTo(u32, gpa, value, endian, obs),
            8 => if (signed) doTo(i64, gpa, value, endian, obs) else doTo(u64, gpa, value, endian, obs),
            else => unreachable,
        };
    }

    const data = fields[5];
    return switch (width) {
        1 => if (signed) doFrom(i8, gpa, data, endian, obs) else doFrom(u8, gpa, data, endian, obs),
        4 => if (signed) doFrom(i32, gpa, data, endian, obs) else doFrom(u32, gpa, data, endian, obs),
        8 => if (signed) doFrom(i64, gpa, data, endian, obs) else doFrom(u64, gpa, data, endian, obs),
        else => unreachable,
    };
}

pub fn main(init: std.process.Init) !void {
    const gpa = init.gpa;
    const io = init.io;
    const args = init.minimal.args.vector;
    if (args.len < 3) {
        std.debug.print("uso: driver <cases.hexl> <obs.zigl>\n", .{});
        return;
    }
    const cases = try lib.readCases(gpa, io, std.mem.span(args[1]));
    defer lib.freeCases(gpa, cases);

    var obs: std.ArrayList(u8) = .empty;
    defer obs.deinit(gpa);
    for (cases) |payload| {
        var f = lib.Fields.init(payload);
        var fields: std.ArrayList([]const u8) = .empty;
        defer fields.deinit(gpa);
        while (f.next()) |item| try fields.append(gpa, item);
        try handle(gpa, fields.items, &obs);
    }
    try lib.writeObs(gpa, io, std.mem.span(args[2]), obs.items);
}
