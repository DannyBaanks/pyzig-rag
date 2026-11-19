const std = @import("std");

fn i32Less(_: void, a: i32, b: i32) bool {
    return a < b;
}

pub fn uniqueSorted(allocator: std.mem.Allocator, xs: []const i32) ![]i32 {
    const out = try allocator.dupe(i32, xs);
    errdefer allocator.free(out);
    std.mem.sort(i32, out, {}, i32Less);
    var w: usize = 0;
    for (out) |v| {
        if (w == 0 or out[w - 1] != v) {
            out[w] = v;
            w += 1;
        }
    }
    return try allocator.realloc(out, w);
}
