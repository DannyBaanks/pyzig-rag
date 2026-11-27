const std = @import("std");

pub fn collectEvens(allocator: std.mem.Allocator, xs: []const i32) ![]i32 {
    var out: std.ArrayList(i32) = .empty;
    errdefer out.deinit(allocator);
    for (xs) |x| {
        if (@rem(x, 2) == 0) try out.append(allocator, x);
    }
    return out.toOwnedSlice(allocator);
}
