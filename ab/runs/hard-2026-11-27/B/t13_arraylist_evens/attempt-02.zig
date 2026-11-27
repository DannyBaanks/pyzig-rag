const std = @import("std");

pub fn collectEvens(allocator: std.mem.Allocator, xs: []const i32) ![]i32 {
    var list: std.ArrayList(i32) = .empty;
    defer list.deinit(allocator);

    for (xs) |x| {
        if (@rem(x, 2) == 0) {
            try list.append(allocator, x);
        }
    }

    return try list.toOwnedSlice(allocator);
}