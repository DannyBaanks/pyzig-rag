const std = @import("std");

pub fn prefixSums(allocator: std.mem.Allocator, xs: []const i64) ![]i64 {
    const out = try allocator.alloc(i64, xs.len);
    var acc: i64 = 0;
    for (xs, 0..) |v, i| {
        acc += v;
        out[i] = acc;
    }
    return out;
}
