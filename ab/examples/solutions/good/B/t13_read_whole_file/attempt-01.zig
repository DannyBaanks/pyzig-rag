const std = @import("std");

pub fn readWhole(allocator: std.mem.Allocator, io: std.Io, dir: std.Io.Dir, sub_path: []const u8) ![]u8 {
    return dir.readFileAlloc(io, sub_path, allocator, .unlimited);
}
