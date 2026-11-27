const std = @import("std");

pub fn writeRow(w: *std.Io.Writer, name: []const u8, value: i64) std.Io.Writer.Error!void {
    try w.print("{s}={d}\n", .{ name, value });
}
