const std = @import("std");

pub fn napMeasured(io: std.Io, ms: i64) std.Io.Cancelable!i64 {
    const clock: std.Io.Clock = .awake;
    const started = clock.now(io);
    try io.sleep(std.Io.Duration.fromMilliseconds(ms), clock);
    const elapsed = started.durationTo(clock.now(io)).toMilliseconds();
    return @max(ms, elapsed);
}
