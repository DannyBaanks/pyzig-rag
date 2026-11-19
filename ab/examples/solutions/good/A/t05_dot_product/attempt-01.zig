const std = @import("std");

pub fn dotProduct(a: []const i32, b: []const i32) i64 {
    var total: i64 = 0;
    const n = @min(a.len, b.len);
    for (0..n) |i| {
        total += @as(i64, a[i]) * @as(i64, b[i]);
    }
    return total;
}
