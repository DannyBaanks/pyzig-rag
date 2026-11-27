const std = @import("std");

const Shared = struct {
    io: std.Io,
    mutex: std.Io.Mutex = .init,
    total: i64 = 0,
};

const Context = struct {
    shared: *Shared,
    chunk: []const i64,
    err: ?anyerror = null,
};

fn worker(ctx: *Context) void {
    var partial: i64 = 0;
    for (ctx.chunk) |v| partial += v;

    ctx.shared.mutex.lock(ctx.shared.io) catch |err| {
        ctx.err = err;
        return;
    };
    defer ctx.shared.mutex.unlock(ctx.shared.io);

    ctx.shared.total += partial;
}

pub fn parallelSum(allocator: std.mem.Allocator, io: std.Io, xs: []const i64, workers: usize) !i64 {
    if (workers == 0) return error.NoWorkers;

    var shared = Shared{ .io = io };
    const chunk_size: usize = if (xs.len == 0) 0 else (xs.len - 1) / workers + 1;

    const threads = try allocator.alloc(std.Thread, workers);
    defer allocator.free(threads);
    const contexts = try allocator.alloc(Context, workers);
    defer allocator.free(contexts);

    var spawned: usize = 0;
    errdefer {
        for (threads[0..spawned]) |t| t.join();
    }

    for (threads, contexts, 0..) |*thread, *ctx, i| {
        const start = @min(i * chunk_size, xs.len);
        const end = start + @min(chunk_size, xs.len - start);
        ctx.* = .{ .shared = &shared, .chunk = xs[start..end] };
        thread.* = try std.Thread.spawn(.{}, worker, .{ctx});
        spawned += 1;
    }

    for (threads) |t| t.join();

    for (contexts) |ctx| {
        if (ctx.err) |err| return err;
    }
    return shared.total;
}
