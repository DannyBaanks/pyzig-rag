const std = @import("std");

pub fn collectEvens(allocator: std.mem.Allocator, xs: []const i32) ![]i32 {
    var list = std.ArrayList(i32).init(allocator);
    defer list.deinit();

    for (xs) |x| {
        if (@rem(x, 2) == 0) {
            try list.append(x);
        }
    }

    return list.toOwnedSlice();
}