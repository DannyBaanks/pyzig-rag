const std = @import("std");

pub fn distinctCount(allocator: std.mem.Allocator, words: []const []const u8) !usize {
    var seen = std.StringHashMap(void).init(allocator);
    defer seen.deinit();

    for (words) |word| {
        try seen.put(word, {});
    }

    return seen.count();
}
