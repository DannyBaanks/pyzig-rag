// Classification of a (subject, oracle) observation pair.
//
// The taxonomy follows the house differential-fuzzer convention: a run either
// agrees, disagrees, crashes, times out, is inconclusive (missing data) or is
// nondeterministic (same input, different answer).
const std = @import("std");
const proto = @import("proto.zig");

pub const Class = enum {
    EQUIV,
    DIVERGENT,
    CRASH,
    TIMEOUT,
    INCONCLUSIVE,
    NONDETERMINISTIC,

    pub fn name(self: Class) []const u8 {
        return @tagName(self);
    }

    /// Classes that count as a finding (a divergence to explain).
    pub fn isDivergence(self: Class) bool {
        return switch (self) {
            .DIVERGENT, .CRASH, .TIMEOUT, .NONDETERMINISTIC => true,
            .EQUIV, .INCONCLUSIVE => false,
        };
    }
};

pub const Diff = struct {
    class: Class,
    status_equal: bool,
    payload_equal: bool,
    first_diff_offset: ?usize,
};

/// Compare one observation pair. `null` means the observation is missing
/// (the process died before writing it) and yields INCONCLUSIVE.
pub fn classify(subject: ?proto.Obs, oracle: ?proto.Obs) Diff {
    const s = subject orelse return .{
        .class = .INCONCLUSIVE,
        .status_equal = false,
        .payload_equal = false,
        .first_diff_offset = null,
    };
    const o = oracle orelse return .{
        .class = .INCONCLUSIVE,
        .status_equal = false,
        .payload_equal = false,
        .first_diff_offset = null,
    };

    const class: Class = switch (s.status) {
        .crash => .CRASH,
        .timeout => .TIMEOUT,
        else => switch (o.status) {
            .crash => .CRASH,
            .timeout => .TIMEOUT,
            else => .EQUIV,
        },
    };

    const status_equal = s.status == o.status;
    const payload_equal = std.mem.eql(u8, s.payload, o.payload);
    const final: Class = if (class != .EQUIV) class else if (status_equal and payload_equal) .EQUIV else .DIVERGENT;

    var offset: ?usize = null;
    if (!payload_equal) {
        const n = @min(s.payload.len, o.payload.len);
        var i: usize = 0;
        while (i < n) : (i += 1) {
            if (s.payload[i] != o.payload[i]) {
                offset = i;
                break;
            }
        }
        if (offset == null and s.payload.len != o.payload.len) offset = n;
    }

    return .{
        .class = final,
        .status_equal = status_equal,
        .payload_equal = payload_equal,
        .first_diff_offset = offset,
    };
}

test "identical observations are EQUIV" {
    const gpa = std.testing.allocator;
    const line = try proto.encodeObsLine(gpa, .ok, &.{ "1", "abc" });
    defer gpa.free(line);
    const a = try proto.parseObsLine(gpa, line);
    defer proto.freeObs(gpa, a);
    const b = try proto.parseObsLine(gpa, line);
    defer proto.freeObs(gpa, b);
    const d = classify(a, b);
    try std.testing.expectEqual(Class.EQUIV, d.class);
    try std.testing.expect(d.status_equal and d.payload_equal);
}

test "different payloads are DIVERGENT with an offset" {
    const gpa = std.testing.allocator;
    const la = try proto.encodeObsLine(gpa, .ok, &.{ "1", "abc" });
    defer gpa.free(la);
    const lb = try proto.encodeObsLine(gpa, .ok, &.{ "1", "abd" });
    defer gpa.free(lb);
    const a = try proto.parseObsLine(gpa, la);
    defer proto.freeObs(gpa, a);
    const b = try proto.parseObsLine(gpa, lb);
    defer proto.freeObs(gpa, b);
    const d = classify(a, b);
    try std.testing.expectEqual(Class.DIVERGENT, d.class);
    // payload = [len("1")][1][len("abc")][abc]: the last byte differs
    try std.testing.expectEqual(@as(?usize, 11), d.first_diff_offset);
}

test "missing observation is INCONCLUSIVE, crash wins over payload" {
    const gpa = std.testing.allocator;
    const line = try proto.encodeObsLine(gpa, .ok, &.{"x"});
    defer gpa.free(line);
    const a = try proto.parseObsLine(gpa, line);
    defer proto.freeObs(gpa, a);
    try std.testing.expectEqual(Class.INCONCLUSIVE, classify(null, a).class);
    try std.testing.expectEqual(Class.INCONCLUSIVE, classify(a, null).class);
}
