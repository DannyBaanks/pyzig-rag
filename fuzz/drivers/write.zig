// Driver: write/v1 — corpus recipe zig0.16/write-file-bytes-atomic
//
// Case:    [mode, pre, data]        mode: truncate | append
// Fields:  status, error, size
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

const TARGET = "out.bin";

fn handle(gpa: std.mem.Allocator, io: std.Io, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 3) return lib.invalid(gpa, obs, 3);
    const mode = fields[0];
    const pre = fields[1];
    const data = fields[2];
    const is_truncate = std.mem.eql(u8, mode, "truncate");
    const is_append = std.mem.eql(u8, mode, "append");
    if (!is_truncate and !is_append) return lib.invalid(gpa, obs, 3);

    var dir = std.Io.Dir.cwd();
    dir.writeFile(io, .{ .sub_path = TARGET, .data = pre }) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "0" });
    };

    if (is_truncate) {
        writeBytes(io, &dir, TARGET, data) catch |err| {
            return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "0" });
        };
    } else {
        // append: concatenar en memoria (std no expone O_APPEND en 0.16)
        const prev = dir.readFileAlloc(io, TARGET, gpa, .limited(16 * 1024 * 1024)) catch |err| {
            return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "0" });
        };
        defer gpa.free(prev);
        const joined = try std.mem.concat(gpa, u8, &.{ prev, data });
        defer gpa.free(joined);
        writeBytes(io, &dir, TARGET, joined) catch |err| {
            return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "0" });
        };
    }

    const final = dir.readFileAlloc(io, TARGET, gpa, .limited(16 * 1024 * 1024)) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "0" });
    };
    defer gpa.free(final);
    var buf: [32]u8 = undefined;
    const size = try std.fmt.bufPrint(&buf, "{d}", .{final.len});
    try lib.appendObs(gpa, obs, "ok", &.{ "ok", "", size });
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
