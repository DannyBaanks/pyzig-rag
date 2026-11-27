// Driver: sortkey/v1 — corpus recipe zig0.16/sorted-key-stable
//
// Case:    [op, rev, item0, item1, ...]
//          op: byage   (rev: "0"|"1"; items son pares name, age_u32)
//              strings (rev: "0"; items son cadenas UTF-8 validas)
// Fields:  status, error, out
const std = @import("std");
const lib = @import("driver_lib.zig");

// @IMPL@

fn parseU32Strict(text: []const u8) ?u32 {
    if (text.len == 0) return null;
    for (text) |c| if (c < '0' or c > '9') return null;
    return std.fmt.parseInt(u32, text, 10) catch null;
}

fn handle(gpa: std.mem.Allocator, fields: []const []const u8, obs: *std.ArrayList(u8)) !void {
    if (fields.len < 2) return lib.invalid(gpa, obs, 3);
    const op = fields[0];
    const rev_s = fields[1];

    if (std.mem.eql(u8, op, "byage")) {
        const rev = if (std.mem.eql(u8, rev_s, "0"))
            false
        else if (std.mem.eql(u8, rev_s, "1"))
            true
        else
            return lib.invalid(gpa, obs, 3);

        const rest = fields[2..];
        if (rest.len % 2 != 0) return lib.invalid(gpa, obs, 3);
        const count = rest.len / 2;
        const people = try gpa.alloc(Person, count);
        defer gpa.free(people);

        for (0..count) |i| {
            const name = rest[2 * i];
            if (!std.unicode.utf8ValidateSlice(name)) return lib.invalid(gpa, obs, 3);
            if (std.mem.indexOfAny(u8, name, ":,") != null) return lib.invalid(gpa, obs, 3);
            const age = parseU32Strict(rest[2 * i + 1]) orelse return lib.invalid(gpa, obs, 3);
            people[i] = .{ .name = name, .age = age };
        }

        const sorted = try sortedByAge(gpa, people, rev);
        defer gpa.free(sorted);

        var out: std.ArrayList(u8) = .empty;
        defer out.deinit(gpa);
        for (sorted, 0..) |p, i| {
            if (i > 0) try out.append(gpa, ',');
            try out.print(gpa, "{s}:{d}", .{ p.name, p.age });
        }
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", out.items });
    }

    if (std.mem.eql(u8, op, "strings")) {
        if (!std.mem.eql(u8, rev_s, "0")) return lib.invalid(gpa, obs, 3);
        const rest = fields[2..];
        for (rest) |s| {
            if (!std.unicode.utf8ValidateSlice(s)) return lib.invalid(gpa, obs, 3);
        }
        const items = try gpa.dupe([]const u8, rest);
        defer gpa.free(items);
        sortStrings(items);
        const packed_out = try lib.packFields(gpa, items);
        defer gpa.free(packed_out);
        const hex = try lib.hexEncode(gpa, packed_out);
        defer gpa.free(hex);
        return lib.appendObs(gpa, obs, "ok", &.{ "ok", "", hex });
    }

    return lib.invalid(gpa, obs, 3);
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
