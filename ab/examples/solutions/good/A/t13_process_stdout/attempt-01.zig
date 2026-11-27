const std = @import("std");

pub fn captureChildStdout(allocator: std.mem.Allocator, io: std.Io, argv: []const []const u8) ![]u8 {
    const res = try std.process.run(allocator, io, .{ .argv = argv });
    defer allocator.free(res.stderr);
    switch (res.term) {
        .exited => |code| if (code == 0) return res.stdout,
        else => {},
    }
    allocator.free(res.stdout);
    return error.ChildFailed;
}
