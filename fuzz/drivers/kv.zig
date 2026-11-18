// Driver: kv/v1 — corpus recipe zig0.16/parse-kv-config
//
// Case:    [text]
// Fields:  status, error, pairs, digest, first_key, first_value
//
// El digest es sha256 de la salida canonica "clave=valor\n" por cada par.
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn handle(gpa: std.mem.Allocator, _: std.Io, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 1) return lib.invalid(gpa, obs, 6);
    const text = fields[0];

    var canonical: std.ArrayList(u8) = .empty;
    defer canonical.deinit(gpa);
    var pairs: usize = 0;
    var first_key: ?[]u8 = null;
    var first_value: ?[]u8 = null;
    defer {
        if (first_key) |k| gpa.free(k);
        if (first_value) |v| gpa.free(v);
    }

    var it = std.mem.splitScalar(u8, text, '\n');
    while (it.next()) |line| {
        // Usa la implementacion inyectada del corpus, no el helper duplicado.
        const kv = (try parseLineAlloc(gpa, line)) orelse continue;
        defer gpa.free(kv.val);
        if (pairs == 0) {
            first_key = try gpa.dupe(u8, kv.key);
            first_value = try gpa.dupe(u8, kv.val);
        }
        pairs += 1;
        try canonical.appendSlice(gpa, kv.key);
        try canonical.append(gpa, '=');
        try canonical.appendSlice(gpa, kv.val);
        try canonical.append(gpa, '\n');
    }

    var digest: [32]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(canonical.items, &digest, .{});
    var hex: [64]u8 = undefined;
    hex = std.fmt.bytesToHex(digest, .lower);

    var pairs_buf: [16]u8 = undefined;
    const pairs_str = try std.fmt.bufPrint(&pairs_buf, "{d}", .{pairs});
    // first_key/first_value como hex para mantener paridad con el modelo Python
    const fk_hex = try lib.hexEncode(gpa, first_key orelse "");
    defer gpa.free(fk_hex);
    const fv_hex = try lib.hexEncode(gpa, first_value orelse "");
    defer gpa.free(fv_hex);
    try lib.appendObs(gpa, obs, "ok", &.{ "ok", "", pairs_str, &hex, fk_hex, fv_hex });
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
