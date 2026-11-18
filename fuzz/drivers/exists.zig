// Driver: exists/v1 — corpus recipe zig0.16/file-exists-vs-error
//
// Case:    [kind, path]      kind: file | missing | dir
// Fields:  status, error, kind
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn handle(gpa: std.mem.Allocator, io: std.Io, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 2) return lib.invalid(gpa, obs, 3);
    const kind = fields[0];
    const path = fields[1];
    if (!lib.validPath(path)) return lib.invalid(gpa, obs, 3);
    const is_file = std.mem.eql(u8, kind, "file");
    const is_missing = std.mem.eql(u8, kind, "missing");
    const is_dir = std.mem.eql(u8, kind, "dir");
    if (!is_file and !is_missing and !is_dir) return lib.invalid(gpa, obs, 3);

    var dir = std.Io.Dir.cwd();
    // Cada caso empieza desde un path inexistente en ambos lados; sin esto
    // los casos comparten estado dentro del chunk y el oracle y el subject
    // se ven mutuamente (el oracle corre antes que el subject).
    dir.deleteTree(io, path) catch {};
    dir.deleteFile(io, path) catch {};
    if (is_file) {
        if (std.fs.path.dirname(path)) |parent| {
            if (parent.len > 0) dir.createDirPath(io, parent) catch {};
        }
        dir.writeFile(io, .{ .sub_path = path, .data = "" }) catch |err| {
            return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "" });
        };
    } else if (is_dir) {
        dir.createDirPath(io, path) catch |err| {
            return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "" });
        };
    }

    const verdict = classify(io, &dir, path);
    const name: []const u8 = switch (verdict) {
        .yes => "yes",
        .missing => "missing",
        .inaccessible => "inaccessible",
    };
    try lib.appendObs(gpa, obs, "ok", &.{ "ok", "", name });
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
