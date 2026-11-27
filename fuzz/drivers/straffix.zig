// Driver: straffix/v1 — corpus recipe zig0.16/str-find-replace-affix
//
// Case:    [op, s, a, b]
//          op: starts | ends | find | replace
//          s, a, b: cadenas UTF-8 validas (UTF-8 invalido -> invalid en ambos lados)
// Fields:  status, error, out
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn errName(err: anyerror) []const u8 {
    return switch (err) {
        error.EmptyNeedle => "EmptyNeedle",
        else => lib.canonError(err),
    };
}

fn handle(gpa: std.mem.Allocator, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 4) return lib.invalid(gpa, obs, 3);
    const op = fields[0];
    const s = fields[1];
    const a = fields[2];
    const b = fields[3];
    if (!std.unicode.utf8ValidateSlice(s) or
        !std.unicode.utf8ValidateSlice(a) or
        !std.unicode.utf8ValidateSlice(b))
    {
        return lib.invalid(gpa, obs, 3);
    }

    if (std.mem.eql(u8, op, "starts")) {
        const res = if (startsWith(s, a)) "1" else "0";
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", res });
    }
    if (std.mem.eql(u8, op, "ends")) {
        const res = if (endsWith(s, a)) "1" else "0";
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", res });
    }
    if (std.mem.eql(u8, op, "find")) {
        var buf: [24]u8 = undefined;
        const res: []const u8 = if (find(s, a)) |idx|
            try std.fmt.bufPrint(&buf, "{d}", .{idx})
        else
            "-1";
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", res });
    }
    if (std.mem.eql(u8, op, "replace")) {
        const out = replaceAll(gpa, s, a, b) catch |err| {
            return lib.appendObs(gpa, obs, "err", &.{ "err", errName(err), "" });
        };
        defer gpa.free(out);
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", out });
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
