// Driver: packint/v1 — corpus recipe zig0.16/struct-pack-endian-readint
//
// Case:    [op, endian, value, offset, data]
//          op: pack | read | readi | write
//          endian: big | little
//          value, offset: enteros i64 decimales (formato estricto); offset >= 0
//          data: bytes del buffer (read/readi/write)
// Fields:  status, error, value, out
//          value: decimal (read/readi); out: hex del buffer o del entero (pack/write)
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

/// Formato estricto compartido con el modelo Python.
fn parseI64(text: []const u8) ?i64 {
    var s = text;
    if (s.len > 0 and s[0] == '-') s = s[1..];
    if (s.len == 0) return null;
    for (s) |c| if (c < '0' or c > '9') return null;
    return std.fmt.parseInt(i64, text, 10) catch null;
}

/// Orden de las comprobaciones (igual que el modelo, que sigue a CPython):
/// formato de los campos (invalid) -> limites del buffer (ShortBuffer) ->
/// rango del valor (OutOfRange).
fn handle(gpa: std.mem.Allocator, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 5) return lib.invalid(gpa, obs, 4);
    const op = fields[0];
    const endian: std.builtin.Endian = if (std.mem.eql(u8, fields[1], "big"))
        .big
    else if (std.mem.eql(u8, fields[1], "little"))
        .little
    else
        return lib.invalid(gpa, obs, 4);
    const value = parseI64(fields[2]) orelse return lib.invalid(gpa, obs, 4);
    const offset = parseI64(fields[3]) orelse return lib.invalid(gpa, obs, 4);
    if (offset < 0) return lib.invalid(gpa, obs, 4);
    const data = fields[4];
    const is_pack = std.mem.eql(u8, op, "pack");
    const is_read = std.mem.eql(u8, op, "read");
    const is_readi = std.mem.eql(u8, op, "readi");
    const is_write = std.mem.eql(u8, op, "write");
    if (!(is_pack or is_read or is_readi or is_write)) return lib.invalid(gpa, obs, 4);

    const off: u64 = @intCast(offset);
    const len: u64 = data.len;
    // 4 bytes desde off: comprobado sin desbordar (off puede ser enorme)
    const fits = off <= len and len - off >= 4;
    const maxU32: i64 = std.math.maxInt(u32);

    if (is_pack) {
        if (value < 0 or value > maxU32) return lib.appendObs(gpa, obs, "err", &.{ "err", "OutOfRange", "", "" });
        var out: [4]u8 = undefined;
        packU32(&out, @intCast(value), endian);
        const hex = try lib.hexEncode(gpa, &out);
        defer gpa.free(hex);
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", "", hex });
    }
    if (is_read or is_readi) {
        if (!fits) return lib.appendObs(gpa, obs, "err", &.{ "err", "ShortBuffer", "", "" });
        const o: usize = @intCast(off);
        var buf: [24]u8 = undefined;
        if (is_read) {
            const v = u32At(data, o, endian) catch |err| return lib.appendObs(gpa, obs, "err", &.{ "err", errName(err), "", "" });
            const s = try std.fmt.bufPrint(&buf, "{d}", .{v});
            return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", s, "" });
        }
        // la receta solo expone unpackU32 en su impl; i32 = mismo patron de bits
        const chunk: *const [4]u8 = data[o..][0..4];
        const v: i32 = @bitCast(unpackU32(chunk, endian));
        const s = try std.fmt.bufPrint(&buf, "{d}", .{v});
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", s, "" });
    }
    // write: el buffer es una copia mutable del campo data; el entero se
    // empaqueta con packU32 (de la receta) y se copia en la posicion. putU32At
    // solo existe en zig_test, no en la impl.
    if (!fits) return lib.appendObs(gpa, obs, "err", &.{ "err", "ShortBuffer", "", "" });
    if (value < 0 or value > maxU32) return lib.appendObs(gpa, obs, "err", &.{ "err", "OutOfRange", "", "" });
    const buf = try gpa.dupe(u8, data);
    defer gpa.free(buf);
    var word: [4]u8 = undefined;
    packU32(&word, @intCast(value), endian);
    @memcpy(buf[@intCast(off)..][0..4], &word);
    const hex = try lib.hexEncode(gpa, buf);
    defer gpa.free(hex);
    return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", "", hex });
}

/// Errores de la receta -> nombres canonicos del modelo Python.
fn errName(err: anyerror) []const u8 {
    return switch (err) {
        error.ShortBuffer => "ShortBuffer",
        else => lib.canonError(err),
    };
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
        try handle(gpa, fields.items, &obs);
    }
    try lib.writeObs(gpa, io, std.mem.span(args[2]), obs.items);
}
