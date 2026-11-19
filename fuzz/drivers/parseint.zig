// Driver: parseint/v1 — corpus recipe zig0.16/parse-int-base-overflow
//
// Case:    [text, base]    base: entero decimal; 0 o 2..36 (otro valor: invalid)
// Fields:  status, error, value    value: i32 en decimal (rango de i32 = tipo destino)
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

/// Python: ValueError (InvalidLiteral) y OverflowError fuera de i32 (Overflow).
fn errName(err: anyerror) []const u8 {
    return switch (err) {
        error.InvalidCharacter => "InvalidLiteral",
        error.Overflow => "Overflow",
        else => lib.canonError(err),
    };
}

fn handle(gpa: std.mem.Allocator, _: std.Io, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 2) return lib.invalid(gpa, obs, 3);
    const text = fields[0];
    const base = std.fmt.parseInt(i64, fields[1], 10) catch return lib.invalid(gpa, obs, 3);
    // parseInt hace panic con una base fuera de 2..36 (0 = detectar): se valida antes
    if (base != 0 and (base < 2 or base > 36)) return lib.invalid(gpa, obs, 3);
    const value = parseI32(text, @intCast(base)) catch |err| {
        return lib.appendObs(gpa, obs, "err", &.{ "err", errName(err), "" });
    };
    var buf: [16]u8 = undefined;
    const s = try std.fmt.bufPrint(&buf, "{d}", .{value});
    return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", s });
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
