// Driver: divmod/v1 — corpus recipe zig0.16/div-floor-mod-negative
//
// Case:    [a, b]     enteros i32 decimales con formato estricto (-?[0-9]+)
// Fields:  status, error, quot, rem
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

/// Formato estricto compartido con el modelo Python: sin '+', espacios ni
/// separadores. parseInt(i32) despues comprueba el rango.
fn parseI32(text: []const u8) ?i32 {
    var s = text;
    if (s.len > 0 and s[0] == '-') s = s[1..];
    if (s.len == 0) return null;
    for (s) |c| if (c < '0' or c > '9') return null;
    return std.fmt.parseInt(i32, text, 10) catch null;
}

fn handle(gpa: std.mem.Allocator, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 2) return lib.invalid(gpa, obs, 4);
    const a = parseI32(fields[0]) orelse return lib.invalid(gpa, obs, 4);
    const b = parseI32(fields[1]) orelse return lib.invalid(gpa, obs, 4);
    // Guardas: en Zig la division por cero y minInt / -1 son panic, y un panic
    // tumbaria el proceso del chunk. Python: ZeroDivisionError; y el cociente
    // 2^31 no cabe en i32 (Overflow, igual que el resto de recetas i32).
    if (b == 0) return lib.appendObs(gpa, obs, "err", &.{ "err", "DivisionByZero", "", "" });
    if (a == std.math.minInt(i32) and b == -1) return lib.appendObs(gpa, obs, "err", &.{ "err", "Overflow", "", "" });
    const q = pyFloorDiv(a, b);
    const r = pyMod(a, b);
    var qbuf: [16]u8 = undefined;
    var rbuf: [16]u8 = undefined;
    const qs = try std.fmt.bufPrint(&qbuf, "{d}", .{q});
    const rs = try std.fmt.bufPrint(&rbuf, "{d}", .{r});
    return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", qs, rs });
}

pub fn main(init: std.process.Init) !void {
    const gpa = init.gpa;
    const args = init.minimal.args.vector;
    if (args.len < 3) {
        std.debug.print("uso: driver <cases.hexl> <obs.zigl>\n", .{});
        return;
    }
    const io = init.io;
    const cases = try lib.readCases(gpa, io, std.mem.span(args[1]));
    defer lib.freeCases(gpa, cases);

    var obs: std.ArrayList(u8) = .empty;
    defer obs.deinit(gpa);
    for (cases) |payload| {
        var f = lib.Fields.init(payload);
        var fields: std.ArrayList([]const u8) = .empty;
        defer fields.deinit(gpa);
        while (f.next()) |item| try fields.append(gpa, item);
        try handle(gpa, fields.items, &obs);
    }
    try lib.writeObs(gpa, io, std.mem.span(args[2]), obs.items);
}
