// Driver: parsefloat/v1 — corpus recipe zig0.16/parse-float-format-decimals
//
// Case:    [op, text]
//          op: parse (text = literal float) | fmt2 (text = 16 hex chars de bits IEEE-754 f64)
// Fields:  status, error, value
//          parse: "nan" si NaN, o 16 hex chars en minusculas de los bits IEEE-754 f64
//          fmt2:  cadena devuelta por fixed2(&buf, x)
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn errName(err: anyerror) []const u8 {
    return switch (err) {
        error.InvalidCharacter => "InvalidLiteral",
        else => lib.canonError(err),
    };
}

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
    const text = fields[1];

    if (std.mem.eql(u8, op, "parse")) {
        const x = parseF64(text) catch |err| {
            return lib.appendObs(gpa, obs, "err", &.{ "err", errName(err), "" });
        };
        if (std.math.isNan(x)) {
            return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", "nan" });
        }
        const bits: u64 = @bitCast(x);
        var buf: [16]u8 = undefined;
        const s = try std.fmt.bufPrint(&buf, "{x:0>16}", .{bits});
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", s });
    }
    if (std.mem.eql(u8, op, "fmt2")) {
        const bits = parseHexU64Strict(text) orelse return lib.invalid(gpa, obs, 3);
        const x: f64 = @bitCast(bits);
        var buf: [512]u8 = undefined;
        const s = fixed2(&buf, x) catch |err| {
            return lib.appendObs(gpa, obs, "err", &.{ "err", errName(err), "" });
        };
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
