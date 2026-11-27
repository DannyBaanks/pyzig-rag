const std = @import("std");

const Shared = struct {
    mutex: std.Io.Mutex = .init,
    total: i64 = 0,
};

const WorkerContext = struct {
    io: std.Io,
    shared: *Shared,
    xs: []const i64,
    start: usize,
    end: usize,
};

fn worker(ctx: WorkerContext) void {
    var partial: i64 = 0;
    for (ctx.xs[ctx.start..ctx.end]) |v| {
        partial +%= v;
    }
    ctx.shared.mutex.lockUncancelable(ctx.io);
    ctx.shared.total +%= partial;
    ctx.shared.mutex.unlock(ctx.io);
}

pub fn parallelSum(allocator: std.mem.Allocator, io: std.Io, xs: []const i64, workers: usize) !i64 {
    if (workers == 0) return error.NoWorkers;

    var shared = Shared{};
    const threads = try allocator.alloc(std.Thread, workers);
    defer allocator.free(threads);

    const chunk = xs.len / workers + @intFromBool(xs.len % workers != 0);

    var spawned: usize = 0;
    errdefer {
        for (threads[0..spawned]) |t| t.join();
    }

    for (0..workers) |i| {
        const start = @min(i *| chunk, xs.len);
        const end = @min(start +| chunk, xs.len);
        threads[i] = try std.Thread.spawn(.{}, worker, .{WorkerContext{
            .io = io,
            .shared = &shared,
            .xs = xs,
            .start = start,
            .end = end,
        }});
        spawned += 1;
    }

    for (threads[0..spawned]) |t| t.join();
    return shared.total;
}
