// Driver: utf8cp/v1 — corpus recipe zig0.16/utf8-codepoints-validate
//
// Case:    [data]   bytes arbitrarios (UTF-8 valido o invalido)
// Fields:  status, error, valid, count, sum
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn errName(err: anyerror) []const u8 {
    return switch (err) {
        error.InvalidUtf8 => "BadEncoding",
        else => lib.canonError(err),
    };
}

fn handle(gpa: std.mem.Allocator, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 1) return lib.invalid(gpa, obs, 5);
    const data = fields[0];
    const valid_s: []const u8 = if (isValidUtf8(data)) "1" else "0";
    const count = countCodepoints(data) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", errName(err), valid_s, "", "" });
    };
    const sum = codepointSum(data) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", errName(err), valid_s, "", "" });
    };
    var cbuf: [24]u8 = undefined;
    var sbuf: [24]u8 = undefined;
    const cs = try std.fmt.bufPrint(&cbuf, "{d}", .{count});
    const ss = try std.fmt.bufPrint(&sbuf, "{d}", .{sum});
    return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", valid_s, cs, ss });
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
