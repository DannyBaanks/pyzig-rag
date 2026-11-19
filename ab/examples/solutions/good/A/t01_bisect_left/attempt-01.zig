const std = @import("std");

pub fn bisectLeft(a: []const i32, x: i32) usize {
    var lo: usize = 0;
    var hi: usize = a.len;
    while (lo < hi) {
        const mid = lo + (hi - lo) / 2;
        if (a[mid] < x) {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    return lo;
}
