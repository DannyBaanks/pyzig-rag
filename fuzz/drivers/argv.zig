// Driver: argv/v1 — corpus recipe zig0.16/subprocess-run-capture
//
// Case:    [prog, arg...]
// Fields:  status, error, term, exit_code, stdout_len, stderr_len
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn handle(gpa: std.mem.Allocator, io: std.Io, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len == 0) return lib.invalid(gpa, obs, 6);
    if (!lib.validProgram(fields[0])) return lib.invalid(gpa, obs, 6);
    for (fields) |arg| {
        if (!lib.validArg(arg)) return lib.invalid(gpa, obs, 6);
    }

    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(gpa);
    for (fields) |arg| try argv.append(gpa, arg);

    const res = runCapture(gpa, io, argv.items) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{
            "err", lib.canonError(err), "spawn_error", "", "0", "0",
        });
    };
    defer {
        gpa.free(res.stdout);
        gpa.free(res.stderr);
    }

    var code_buf: [16]u8 = undefined;
    const term: []const u8, const code: []const u8 = switch (res.term) {
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
    var out_buf: [32]u8 = undefined;
    var err_buf: [32]u8 = undefined;
    const stdout_len = try std.fmt.bufPrint(&out_buf, "{d}", .{res.stdout.len});
    const stderr_len = try std.fmt.bufPrint(&err_buf, "{d}", .{res.stderr.len});
    try lib.appendObs(gpa, obs, "ok", &.{ "ok", "", term, code, stdout_len, stderr_len });
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
