// Driver: roundfloat/v1 — corpus recipe zig0.16/round-floor-ceil-bankers
//
// Case:    [op, hex_bits]
//          op: round_even | floor | ceil | zig_round
//          hex_bits: 16 hex chars en minusculas de un f64 IEEE-754
// Fields:  status, error, value
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn parseHexU64Strict(text: []const u8) ?u64 {
    if (text.len != 16) return null;
    for (text) |c| {
        const ok = (c >= '0' and c <= '9') or (c >= 'a' and c <= 'f');
        if (!ok) return null;
    }
    return std.fmt.parseInt(u64, text, 16) catch null;
}

fn handle(gpa: std.mem.Allocator, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 2) return lib.invalid(gpa, obs, 3);
    const op = fields[0];
    const bits = parseHexU64Strict(fields[1]) orelse return lib.invalid(gpa, obs, 3);
    const x: f64 = @bitCast(bits);

    const r: f64 = if (std.mem.eql(u8, op, "round_even"))
        roundHalfEven(x)
    else if (std.mem.eql(u8, op, "floor"))
        zigFloor(x)
    else if (std.mem.eql(u8, op, "ceil"))
        zigCeil(x)
    else if (std.mem.eql(u8, op, "zig_round"))
        zigRound(x)
    else
        return lib.invalid(gpa, obs, 3);

    if (std.math.isNan(r)) {
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", "nan" });
    }
    if (std.math.isPositiveInf(r)) {
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", "inf" });
    }
    if (std.math.isNegativeInf(r)) {
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", "-inf" });
    }
    var buf: [512]u8 = undefined;
    const s = try std.fmt.bufPrint(&buf, "{d:.0}", .{r});
    return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", s });
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
