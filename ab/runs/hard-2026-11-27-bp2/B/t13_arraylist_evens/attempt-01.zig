const std = @import("std");

pub fn collectEvens(allocator: std.mem.Allocator, xs: []const i32) ![]i32 {
    var evens = std.ArrayList(i32).empty;
    defer evens.deinit(allocator);

    for (xs) |x| {
        if (@rem(x, 2) == 0) {
            try evens.append(allocator, x);
        }
    }

    return try evens.toOwnedSlice(allocator);
}
