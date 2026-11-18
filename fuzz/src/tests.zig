// Test root: pulls the unit tests of every engine module.
const std = @import("std");

test {
    _ = @import("rng.zig");
    _ = @import("proto.zig");
    _ = @import("gen.zig");
    _ = @import("compare.zig");
    _ = @import("evidence.zig");
    _ = @import("runner.zig");
}
