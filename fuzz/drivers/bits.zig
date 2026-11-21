// Driver: bits/v1 — corpus recipe zig0.16/int-bit-count-bit-length
//
// Case:    [op, text]   op: count (bit_count con signo) | length (bit_length)
//                       text: i64 decimal con formato estricto (-?[0-9]+)
// Fields:  status, error, value
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

/// Formato estricto compartido con el modelo Python.
fn parseI64(text: []const u8) ?i64 {
    var s = text;
    if (s.len > 0 and s[0] == '-') s = s[1..];
    if (s.len == 0) return null;
    for (s) |c| if (c < '0' or c > '9') return null;
    return std.fmt.parseInt(i64, text, 10) catch null;
}

fn handle(gpa: std.mem.Allocator, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 2) return lib.invalid(gpa, obs, 3);
    const op = fields[0];
    const x = parseI64(fields[1]) orelse return lib.invalid(gpa, obs, 3);
    var buf: [24]u8 = undefined;
    if (std.mem.eql(u8, op, "count")) {
        const s = try std.fmt.bufPrint(&buf, "{d}", .{bitCountSigned(x)});
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", s });
    }
    if (std.mem.eql(u8, op, "length")) {
        // Magnitud sin desbordar (incluido minInt): bit_length usa abs(x).
        const mag: u64 = if (x < 0) @as(u64, @bitCast(-(x + 1))) + 1 else @intCast(x);
        const s = try std.fmt.bufPrint(&buf, "{d}", .{bitLength(mag)});
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", s });
    }
    return lib.invalid(gpa, obs, 3);
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
