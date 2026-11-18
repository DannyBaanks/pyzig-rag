// Driver: splitfmt/v1 — corpus recipe zig0.16/string-split-strip-format
//
// Case:    [sep, text, mac, ip, width]
// Fields:  status, error, tokens, formatted
//
// `formatted` es f"{mac:<width}|{ip}" (relleno a la derecha, sin truncar).
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn handle(gpa: std.mem.Allocator, _: std.Io, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 5) return lib.invalid(gpa, obs, 4);
    const sep = fields[0];
    const text = fields[1];
    const mac = fields[2];
    const ip = fields[3];
    const width_str = fields[4];
    if (sep.len != 1) return lib.invalid(gpa, obs, 4);
    const width = std.fmt.parseInt(usize, width_str, 10) catch return lib.invalid(gpa, obs, 4);

    const toks = collectNonEmpty(gpa, text, sep[0]) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "", "" });
    };
    defer gpa.free(toks);

    var tail_buf: [512]u8 = undefined;
    const tail = std.fmt.bufPrint(&tail_buf, "|{s}", .{ip}) catch return lib.invalid(gpa, obs, 4);
    var fmt_buf: [512]u8 = undefined;
    const formatted = formatPadded(&fmt_buf, mac, width, tail) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", lib.canonError(err), "", "" });
    };

    var tokens_buf: [16]u8 = undefined;
    const tokens_str = try std.fmt.bufPrint(&tokens_buf, "{d}", .{toks.len});
    try lib.appendObs(gpa, obs, "ok", &.{ "ok", "", tokens_str, formatted });
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
