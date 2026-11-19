const std = @import("std");

fn i64Less(_: void, a: i64, b: i64) bool {
    return a < b;
}

pub fn median(allocator: std.mem.Allocator, xs: []const i64) !f64 {
    if (xs.len == 0) return error.EmptyInput;
    const copy = try allocator.dupe(i64, xs);
    defer allocator.free(copy);
    std.mem.sort(i64, copy, {}, i64Less);
    if (xs.len % 2 == 1) return @floatFromInt(copy[xs.len / 2]);
    const lo: f64 = @floatFromInt(copy[xs.len / 2 - 1]);
    const hi: f64 = @floatFromInt(copy[xs.len / 2]);
    return (lo + hi) / 2.0;
}
