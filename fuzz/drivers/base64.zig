// Driver: base64/v1 — corpus recipe zig0.16/base64-encode-decode
//
// Case:    [op, data]     op: enc | dec
// Fields:  status, error, out
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

/// El modelo Python (binascii.Error) no distingue relleno de caracter: ambos
/// lados colapsan los dos errores de decodificacion en BadEncoding.
fn errName(err: anyerror) []const u8 {
    return switch (err) {
        error.InvalidPadding, error.InvalidCharacter => "BadEncoding",
        else => lib.canonError(err),
    };
}

fn handle(gpa: std.mem.Allocator, _: std.Io, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 2) return lib.invalid(gpa, obs, 3);
    const op = fields[0];
    const data = fields[1];
    if (std.mem.eql(u8, op, "enc")) {
        const out = b64Encode(gpa, data) catch |err| return lib.appendObs(gpa, obs, "err", &.{ "err", errName(err), "" });
        defer gpa.free(out);
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", out });
    }
    if (std.mem.eql(u8, op, "dec")) {
        const out = b64Decode(gpa, data) catch |err| return lib.appendObs(gpa, obs, "err", &.{ "err", errName(err), "" });
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
        try handle(gpa, io, fields.items, &obs);
    }
    try lib.writeObs(gpa, io, std.mem.span(args[2]), obs.items);
}
