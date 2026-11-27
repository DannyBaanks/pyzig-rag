const std = @import("std");

pub fn captureChildStdout(allocator: std.mem.Allocator, io: std.Io, argv: []const []const u8) ![]u8 {
    const result = try std.process.run(allocator, io, .{ .argv = argv });
    defer allocator.free(result.stderr);

    switch (result.term) {
        .exited => |code| {
            if (code == 0) return result.stdout;
        },
        else => {},
    }

    allocator.free(result.stdout);
    return error.ChildFailed;
}
