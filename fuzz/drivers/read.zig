// Driver: read/v1 — corpus recipe zig0.16/read-file-text-limited
//
// Case:    [path, present, content, limit]   present: 0=ausente 1=archivo 2=dir
// Fields:  status, error, size
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn prepare(io: std.Io, dir: *std.Io.Dir, path: []const u8, present: []const u8, content: []const u8) !void {
    if (std.mem.eql(u8, present, "1")) {
        if (std.fs.path.dirname(path)) |parent| {
            if (parent.len > 0) try dir.createDirPath(io, parent);
        }
        try dir.writeFile(io, .{ .sub_path = path, .data = content });
    } else if (std.mem.eql(u8, present, "2")) {
        try dir.createDirPath(io, path);
    }
}

fn handle(gpa: std.mem.Allocator, io: std.Io, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 4) return lib.invalid(gpa, obs, 3);
    const path = fields[0];
    const present = fields[1];
    const content = fields[2];
    const limit_str = fields[3];
    if (!lib.validPath(path)) return lib.invalid(gpa, obs, 3);
    const limit = std.fmt.parseInt(usize, limit_str, 10) catch return lib.invalid(gpa, obs, 3);

    var dir = std.Io.Dir.cwd();
    prepare(io, &dir, path, present, content) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "0" });
    };

    const data = readText(gpa, io, &dir, path, limit) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "0" });
    };
    defer gpa.free(data);
    var buf: [32]u8 = undefined;
    const size = try std.fmt.bufPrint(&buf, "{d}", .{data.len});
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
