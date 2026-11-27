const std = @import("std");

const Shared = struct {
    mu: std.Io.Mutex = .init,
    total: i64 = 0,
};

fn worker(io: std.Io, sh: *Shared, part: []const i64) void {
    var local: i64 = 0;
    for (part) |v| local += v;
    sh.mu.lockUncancelable(io);
    defer sh.mu.unlock(io);
    sh.total += local;
}

pub fn parallelSum(allocator: std.mem.Allocator, io: std.Io, xs: []const i64, workers: usize) !i64 {
    if (workers == 0) return error.NoWorkers;
    var shared: Shared = .{};
    const threads = try allocator.alloc(std.Thread, workers);
    defer allocator.free(threads);
    const chunk = (xs.len + workers - 1) / workers;
    var spawned: usize = 0;
    errdefer for (threads[0..spawned]) |t| t.join();
    for (threads, 0..) |*t, i| {
        const start = @min(i * chunk, xs.len);
        const end = @min(start + chunk, xs.len);
        t.* = try std.Thread.spawn(.{}, worker, .{ io, &shared, xs[start..end] });
        spawned += 1;
    }
    for (threads[0..spawned]) |t| t.join();
    return shared.total;
}
