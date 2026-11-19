const std = @import("std");

pub fn longestTrueRun(bits: []const bool) usize {
    var best: usize = 0;
    var current: usize = 0;
    for (bits) |b| {
        if (b) {
            current += 1;
            if (current > best) best = current;
        } else {
            current = 0;
        }
    }
    return best;
}
