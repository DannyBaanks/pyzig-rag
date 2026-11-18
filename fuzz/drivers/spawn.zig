// Driver: spawn/v1 — corpus recipe zig0.16/spawn-redirect-child
//
// Case:    [pre, prog, arg...]
// Fields:  status, error, term, exit_code, log_len, log_digest
//
// `pre` es el contenido previo del log: el hijo debe APENDAR, no sobrescribir.
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

const LOG = "child.log";

fn handle(gpa: std.mem.Allocator, io: std.Io, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 2) return lib.invalid(gpa, obs, 6);
    const pre = fields[0];
    const prog = fields[1];
    if (!lib.validProgram(prog)) return lib.invalid(gpa, obs, 6);
    for (fields[1..]) |arg| {
        if (!lib.validArg(arg)) return lib.invalid(gpa, obs, 6);
    }

    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(gpa);
    for (fields[1..]) |arg| try argv.append(gpa, arg);

    var dir = std.Io.Dir.cwd();
    dir.writeFile(io, .{ .sub_path = LOG, .data = pre }) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "", "", "0", "" });
    };

    var child = spawnRedirected(io, &dir, LOG, argv.items) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "spawn_error", "", "0", "" });
    };
    const term = child.wait(io) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "spawn_error", "", "0", "" });
    };

    const log = dir.readFileAlloc(io, LOG, gpa, .limited(16 * 1024 * 1024)) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "", "", "0", "" });
    };
    defer gpa.free(log);

    var digest: [32]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(log, &digest, .{});
    var hex: [64]u8 = undefined;
    hex = std.fmt.bytesToHex(digest, .lower);

    var code_buf: [16]u8 = undefined;
    const term_name: []const u8, const code: []const u8 = switch (term) {
        .exited => |c| blk: {
            break :blk .{ "exited", try std.fmt.bufPrint(&code_buf, "{d}", .{c}) };
        },
        .signal => |s| blk: {
            break :blk .{ "signal", try std.fmt.bufPrint(&code_buf, "{d}", .{@intFromEnum(s)}) };
        },
        .stopped => |s| blk: {
            break :blk .{ "stopped", try std.fmt.bufPrint(&code_buf, "{d}", .{@intFromEnum(s)}) };
        },
        .unknown => |c| blk: {
            break :blk .{ "unknown", try std.fmt.bufPrint(&code_buf, "{d}", .{c}) };
        },
    };
    var len_buf: [32]u8 = undefined;
    const log_len = try std.fmt.bufPrint(&len_buf, "{d}", .{log.len});
    try lib.appendObs(gpa, obs, "ok", &.{ "ok", "", term_name, code, log_len, &hex });
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
