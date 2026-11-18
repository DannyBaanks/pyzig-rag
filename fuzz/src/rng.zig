// Deterministic RNG: same seed -> same stream, independent of wall clock or
// process state. Boundary-biased helpers follow the WINS fuzzer house style
// (prefer 0/1/max/max-1 over uniform samples).
const std = @import("std");

pub const Rng = struct {
    inner: std.Random.DefaultPrng,

    pub fn init(seed: u64) Rng {
        return .{ .inner = std.Random.DefaultPrng.init(seed) };
    }

    /// Derive an independent stream from a base seed and a label. Stable: the
    /// label is hashed, never the address or the process id.
    pub fn fork(seed: u64, label: []const u8) Rng {
        const h = std.hash.Wyhash.hash(0, label);
        return init(seed ^ h);
    }

    pub fn random(self: *Rng) std.Random {
        return self.inner.random();
    }

    pub fn below(self: *Rng, n: usize) usize {
        if (n == 0) return 0;
        return self.random().uintLessThan(usize, n);
    }

    pub fn chance(self: *Rng, num: u32, den: u32) bool {
        if (den == 0) return false;
        return self.random().uintLessThan(u32, den) < num;
    }

    pub fn pick(self: *Rng, comptime T: type, items: []const T) T {
        std.debug.assert(items.len > 0);
        return items[self.below(items.len)];
    }

    pub fn fill(self: *Rng, out: []u8) void {
        self.random().bytes(out);
    }

    /// 0, 1, 2, max, max-1 or uniform: the boundary cases a differential
    /// fuzzer must hit before it spends budget on the middle of the range.
    pub fn boundaryLen(self: *Rng, max: usize) usize {
        const m = self.below(10);
        return switch (m) {
            0 => 0,
            1 => 1,
            2 => 2,
            3 => max,
            4 => if (max > 0) max - 1 else 0,
            5 => if (max > 1) max - 2 else 0,
            else => self.below(max + 1),
        };
    }

    pub fn boundaryU64(self: *Rng, max: u64) u64 {
        const m = self.below(8);
        return switch (m) {
            0 => 0,
            1 => 1,
            2 => max,
            3 => if (max > 0) max - 1 else 0,
            else => self.random().uintLessThan(u64, max +| 1),
        };
    }

    pub fn ascii(self: *Rng, out: []u8, charset: []const u8) void {
        for (out) |*b| b.* = self.pick(u8, charset);
    }
};

/// Byte alphabet that stresses the boundaries of text pipelines: NUL, DEL,
/// CRLF, quotes, separators, high-bit bytes and a couple of valid UTF-8
/// sequences.
pub const noisy_charset = "\x00\x01\t\n\r'\"#=,;: \x7f\x80\xffabcXYZ019_-";

test "same seed gives same stream, different seed diverges" {
    var a = Rng.init(42);
    var b = Rng.init(42);
    var c = Rng.init(43);
    var buf_a: [64]u8 = undefined;
    var buf_b: [64]u8 = undefined;
    var buf_c: [64]u8 = undefined;
    a.fill(&buf_a);
    b.fill(&buf_b);
    c.fill(&buf_c);
    try std.testing.expectEqualSlices(u8, &buf_a, &buf_b);
    try std.testing.expect(!std.mem.eql(u8, &buf_a, &buf_c));
}

test "fork is stable and label-dependent" {
    var a = Rng.fork(7, "argv/v1");
    var b = Rng.fork(7, "argv/v1");
    var c = Rng.fork(7, "kv/v1");
    const x = a.random().int(u64);
    const y = b.random().int(u64);
    const z = c.random().int(u64);
    try std.testing.expectEqual(x, y);
    try std.testing.expect(x != z);
}

test "boundaryLen hits the edges" {
    var r = Rng.init(5);
    var saw_zero = false;
    var saw_max = false;
    var i: usize = 0;
    while (i < 200) : (i += 1) {
        const n = r.boundaryLen(16);
        if (n == 0) saw_zero = true;
        if (n == 16) saw_max = true;
        try std.testing.expect(n <= 16);
    }
    try std.testing.expect(saw_zero and saw_max);
}
