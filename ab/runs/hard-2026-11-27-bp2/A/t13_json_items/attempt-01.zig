const std = @import("std");

pub const Item = struct { name: []const u8, qty: i64 };

const Root = struct {
    items: []const Item,
};

pub fn totalQty(allocator: std.mem.Allocator, json_text: []const u8) !i64 {
    const parsed = try std.json.parseFromSlice(Root, allocator, json_text, .{
        .ignore_unknown_fields = true,
    });
    defer parsed.deinit();

    var total: i64 = 0;
    for (parsed.value.items) |item| {
        total +%= item.qty;
    }
    return total;
}
