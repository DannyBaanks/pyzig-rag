const std = @import("std");

pub fn napMeasured(io: std.Io, ms: i64) std.Io.Cancelable!i64 {
    const clock: std.Io.Clock = .awake;
    const start = std.Io.Timestamp.now(io, clock);
    try std.Io.sleep(io, std.Io.Duration.fromMilliseconds(ms), clock);
    const end = std.Io.Timestamp.now(io, clock);
    return @max(start.durationTo(end).toMilliseconds(), ms);
}
