const std = @import("std");

fn lessThan(_: void, a: i32, b: i32) bool {
    return a < b;
}

pub fn uniqueSorted(allocator: std.mem.Allocator, xs: []const i32) ![]i32 {
    const out = try allocator.dupe(i32, xs);
    errdefer allocator.free(out);

    std.mem.sort(i32, out, {}, lessThan);

    var n: usize = 0;
    for (out) |x| {
        if (n == 0 or out[n - 1] != x) {
            out[n] = x;
            n += 1;
        }
    }

    return try allocator.realloc(out, n);
}
