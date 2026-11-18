// Driver: stdout/v1 — corpus recipe zig0.16/stdout-print-flush
//
// Case:    [stream, msg]      stream: out | err
// Fields:  status, error, stream, written
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn handle(gpa: std.mem.Allocator, io: std.Io, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 2) return lib.invalid(gpa, obs, 4);
    const stream = fields[0];
    const msg = fields[1];
    const is_out = std.mem.eql(u8, stream, "out");
    const is_err = std.mem.eql(u8, stream, "err");
    if (!is_out and !is_err) return lib.invalid(gpa, obs, 4);

    if (is_out) {
        out(io, "{s}", .{msg}) catch |err| {
            return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), stream, "0" });
        };
    } else {
        outErr(io, "{s}", .{msg}) catch |err| {
            return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), stream, "0" });
        };
    }

    var buf: [32]u8 = undefined;
    const written = try std.fmt.bufPrint(&buf, "{d}", .{msg.len});
    try lib.appendObs(gpa, obs, "ok", &.{ "ok", "", stream, written });
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
