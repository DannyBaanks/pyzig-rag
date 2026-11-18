// Driver: sha256/v1 — corpus recipe zig0.16/sha256-bytes
//
// Case:    [data]
// Fields:  status, error, digest
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn handle(gpa: std.mem.Allocator, _: std.Io, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 1) return lib.invalid(gpa, obs, 3);
    const hex = sha256Hex(fields[0]);
    try lib.appendObs(gpa, obs, "ok", &.{ "ok", "", &hex });
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
