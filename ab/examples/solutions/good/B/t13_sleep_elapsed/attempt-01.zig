const std = @import("std");

pub fn napMeasured(io: std.Io, ms: i64) std.Io.Cancelable!i64 {
    const t0 = std.Io.Clock.awake.now(io);
    try std.Io.sleep(io, .fromMilliseconds(ms), .awake);
    const t1 = std.Io.Clock.awake.now(io);
    return t0.durationTo(t1).toMilliseconds();
}
