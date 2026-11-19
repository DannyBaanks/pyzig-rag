const std = @import("std");

pub fn xorFold(bytes: []const u8) u8 {
    var acc: u8 = 0;
    for (bytes) |b| acc ^= b;
    return acc;
}
