// Classification of a (subject, oracle) observation pair.
//
// The taxonomy is the house one (AutoPiton differential fuzzer): a run either
// agrees, disagrees, is unsupported on one side, gets an invalid case, accepts
// an invalid case, crashes, times out, is inconclusive (missing data) or is
// nondeterministic (same input, different answer).
//
// Comparison is BY NAMED FIELD, never by raw blob: the schema's contract
// (`fuzz.compared_fields` in the corpus) fixes the field order and both sides
// emit the same names, so a divergence says *which* semantic differs.
const std = @import("std");
const proto = @import("proto.zig");

pub const Class = enum {
    EQUIV,
    DIVERGENT,
    UNSUPPORTED,
    INVALID_REFERENCE,
    INVALID_ACCEPTED,
    CRASH,
    TIMEOUT,
    INCONCLUSIVE,
    NONDETERMINISTIC,

    pub fn name(self: Class) []const u8 {
        return @tagName(self);
    }

    /// Classes that count as a finding (something to explain and fix).
    pub fn isDivergence(self: Class) bool {
        return switch (self) {
            .DIVERGENT, .CRASH, .TIMEOUT, .INVALID_ACCEPTED, .NONDETERMINISTIC => true,
            .EQUIV, .INCONCLUSIVE, .UNSUPPORTED, .INVALID_REFERENCE => false,
        };
    }

    /// Classes where the case itself was not usable for the comparison.
    pub fn isCaseRejected(self: Class) bool {
        return switch (self) {
            .UNSUPPORTED, .INVALID_REFERENCE, .INCONCLUSIVE => true,
            else => false,
        };
    }
};

pub const FieldDiff = struct {
    name: []const u8,
    subject: []const u8,
    oracle: []const u8,
};

pub const Diff = struct {
    class: Class,
    field_diffs: []FieldDiff,
    status_equal: bool,

    pub fn deinit(self: Diff, gpa: std.mem.Allocator) void {
        gpa.free(self.field_diffs);
    }
};

/// Compare one observation pair field by field.
///
/// `names` is the schema's compared-field list (the corpus contract). The
/// observations carry the same fields in the same order.
pub fn classifyFields(
    gpa: std.mem.Allocator,
    names: []const []const u8,
    subject: ?proto.Obs,
    oracle: ?proto.Obs,
) !Diff {
    const s = subject orelse return .{ .class = .INCONCLUSIVE, .field_diffs = &.{}, .status_equal = false };
    const o = oracle orelse return .{ .class = .INCONCLUSIVE, .field_diffs = &.{}, .status_equal = false };

    if (s.status == .crash) return .{ .class = .CRASH, .field_diffs = &.{}, .status_equal = false };
    if (s.status == .timeout) return .{ .class = .TIMEOUT, .field_diffs = &.{}, .status_equal = false };
    if (s.status == .unsupported or o.status == .unsupported) {
        return .{ .class = .UNSUPPORTED, .field_diffs = &.{}, .status_equal = s.status == o.status };
    }
    // The oracle rejected the case as invalid but the subject took it as valid.
    if (o.status == .invalid and s.status == .ok) {
        return .{ .class = .INVALID_ACCEPTED, .field_diffs = &.{}, .status_equal = false };
    }

    var diffs: std.ArrayList(FieldDiff) = .empty;
    errdefer diffs.deinit(gpa);

    var sf = s.fields;
    var of = o.fields;
    for (names) |name| {
        const sv = sf.next() orelse "";
        const ov = of.next() orelse "";
        if (!std.mem.eql(u8, sv, ov)) {
            try diffs.append(gpa, .{ .name = name, .subject = sv, .oracle = ov });
        }
    }
    // Extra fields on either side are also a difference.
    while (sf.next()) |sv| {
        try diffs.append(gpa, .{ .name = "extra", .subject = sv, .oracle = "" });
    }
    while (of.next()) |ov| {
        try diffs.append(gpa, .{ .name = "extra", .subject = "", .oracle = ov });
    }

    return .{
        .class = if (diffs.items.len == 0) .EQUIV else .DIVERGENT,
        .field_diffs = try diffs.toOwnedSlice(gpa),
        .status_equal = s.status == o.status,
    };
}

/// Compare two observations of the SAME side (replay): different answers for
/// the same input mean the side is not deterministic.
pub fn isStable(a: proto.Obs, b: proto.Obs) bool {
    if (a.status != b.status) return false;
    if (!std.mem.eql(u8, a.payload, b.payload)) return false;
    return true;
}

test "identical observations are EQUIV" {
    const gpa = std.testing.allocator;
    const line = try proto.encodeObsLine(gpa, .ok, &.{ "ok", "", "exited", "0", "3", "0" });
    defer gpa.free(line);
    const a = try proto.parseObsLine(gpa, line);
    defer proto.freeObs(gpa, a);
    const b = try proto.parseObsLine(gpa, line);
    defer proto.freeObs(gpa, b);
    const names = [_][]const u8{ "status", "error", "term", "exit_code", "stdout_len", "stderr_len" };
    var d = try classifyFields(gpa, &names, a, b);
    defer d.deinit(gpa);
    try std.testing.expectEqual(Class.EQUIV, d.class);
    try std.testing.expect(d.status_equal);
}

test "different payloads are DIVERGENT with the field that differs" {
    const gpa = std.testing.allocator;
    const la = try proto.encodeObsLine(gpa, .ok, &.{ "ok", "", "exited", "0", "3", "0" });
    defer gpa.free(la);
    const lb = try proto.encodeObsLine(gpa, .ok, &.{ "ok", "", "exited", "7", "3", "0" });
    defer gpa.free(lb);
    const a = try proto.parseObsLine(gpa, la);
    defer proto.freeObs(gpa, a);
    const b = try proto.parseObsLine(gpa, lb);
    defer proto.freeObs(gpa, b);
    const names = [_][]const u8{ "status", "error", "term", "exit_code", "stdout_len", "stderr_len" };
    var d = try classifyFields(gpa, &names, a, b);
    defer d.deinit(gpa);
    try std.testing.expectEqual(Class.DIVERGENT, d.class);
    try std.testing.expectEqual(@as(usize, 1), d.field_diffs.len);
    try std.testing.expectEqualStrings("exit_code", d.field_diffs[0].name);
    try std.testing.expectEqualStrings("0", d.field_diffs[0].subject);
    try std.testing.expectEqualStrings("7", d.field_diffs[0].oracle);
}

test "missing observation is INCONCLUSIVE, crash wins over payload" {
    const gpa = std.testing.allocator;
    const line = try proto.encodeObsLine(gpa, .ok, &.{"ok"});
    defer gpa.free(line);
    const a = try proto.parseObsLine(gpa, line);
    defer proto.freeObs(gpa, a);
    const names = [_][]const u8{"status"};
    var d1 = try classifyFields(gpa, &names, null, a);
    defer d1.deinit(gpa);
    try std.testing.expectEqual(Class.INCONCLUSIVE, d1.class);
    var d2 = try classifyFields(gpa, &names, a, null);
    defer d2.deinit(gpa);
    try std.testing.expectEqual(Class.INCONCLUSIVE, d2.class);
}

test "oracle rejects an invalid case the subject accepted" {
    const gpa = std.testing.allocator;
    const invalid = try proto.encodeObsLine(gpa, .invalid, &.{ "invalid", "limit no numerico" });
    defer gpa.free(invalid);
    const accepted = try proto.encodeObsLine(gpa, .ok, &.{ "ok", "", "0" });
    defer gpa.free(accepted);
    const a = try proto.parseObsLine(gpa, invalid);
    defer proto.freeObs(gpa, a);
    const b = try proto.parseObsLine(gpa, accepted);
    defer proto.freeObs(gpa, b);
    const names = [_][]const u8{ "status", "error", "size" };
    var d = try classifyFields(gpa, &names, b, a);
    defer d.deinit(gpa);
    try std.testing.expectEqual(Class.INVALID_ACCEPTED, d.class);
}

test "unsupported on either side is not a finding" {
    const gpa = std.testing.allocator;
    const uns = try proto.encodeObsLine(gpa, .unsupported, &.{ "unsupported", "sin setsid" });
    defer gpa.free(uns);
    const ok = try proto.encodeObsLine(gpa, .ok, &.{ "ok", "" });
    defer gpa.free(ok);
    const a = try proto.parseObsLine(gpa, uns);
    defer proto.freeObs(gpa, a);
    const b = try proto.parseObsLine(gpa, ok);
    defer proto.freeObs(gpa, b);
    const names = [_][]const u8{ "status", "error" };
    var d = try classifyFields(gpa, &names, a, b);
    defer d.deinit(gpa);
    try std.testing.expectEqual(Class.UNSUPPORTED, d.class);
    try std.testing.expect(!d.class.isDivergence());
}
