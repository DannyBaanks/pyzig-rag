const std = @import("std");

fn isAsciiSpace(c: u8) bool {
    return switch (c) {
        ' ', '\t', '\n', '\r', 0x0b, 0x0c => true,
        else => false,
    };
}

pub fn wordCount(s: []const u8) usize {
    var count: usize = 0;
    var in_word = false;
    for (s) |c| {
        if (isAsciiSpace(c)) {
            in_word = false;
        } else if (!in_word) {
            in_word = true;
            count += 1;
        }
    }
    return count;
}
