const std = @import("std");

pub fn wordCount(s: []const u8) usize {
    var count: usize = 0;
    var in_word = false;
    for (s) |c| {
        const space = c == ' ' or c == '\t' or c == '\n' or c == '\r' or c == 0x0b or c == 0x0c;
        if (space) {
            in_word = false;
        } else if (!in_word) {
            count += 1;
            in_word = true;
        }
    }
    return count;
}
