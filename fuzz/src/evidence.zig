// Evidence helpers: content hashes, JSON escaping and the on-disk run layout.
//
// Run layout (mirrors the house differential-fuzzer convention):
//   <run-dir>/meta.json      configuration + environment
//   <run-dir>/results.jsonl  one record per case that is not EQUIV
//   <run-dir>/summary.json   counters, throughput and digests
const std = @import("std");

pub fn sha256Hex(bytes: []const u8) [64]u8 {
    var digest: [32]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(bytes, &digest, .{});
    var hex: [64]u8 = undefined;
    @memcpy(&hex, &std.fmt.bytesToHex(digest, .lower));
    return hex;
}

/// Read an absolute path (or null when it does not exist).
pub fn readFileAbs(io: std.Io, gpa: std.mem.Allocator, path: []const u8, limit: usize) !?[]u8 {
    const dir_name = std.fs.path.dirname(path) orelse return null;
    const base = std.fs.path.basename(path);
    var dir = std.Io.Dir.openDirAbsolute(io, dir_name, .{}) catch return null;
    defer dir.close(io);
    return dir.readFileAlloc(io, base, gpa, .limited(limit)) catch null;
}

pub fn sha256File(io: std.Io, gpa: std.mem.Allocator, path: []const u8) !?[]u8 {
    const bytes = (try readFileAbs(io, gpa, path, 256 * 1024 * 1024)) orelse return null;
    defer gpa.free(bytes);
    return try gpa.dupe(u8, &sha256Hex(bytes));
}

/// Minimal JSON string escaping (quotes, backslash, control chars).
///
/// Los valores que se escapan son bytes OBSERVADOS (datos fuzzeados), no
/// texto: cualquier byte >= 0x7F dejaria results.jsonl sin UTF-8 valido y el
/// registro con hash seria ilegible para cualquier JSON parser. Se escapea
/// tambien todo lo no-ASCII como \u00XX (los bytes se tratan como latin-1,
/// que es una bijeccion: no se pierde informacion).
pub fn jsonEscape(gpa: std.mem.Allocator, s: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(gpa);
    for (s) |c| {
        switch (c) {
            '"' => try out.appendSlice(gpa, "\\\""),
            '\\' => try out.appendSlice(gpa, "\\\\"),
            '\n' => try out.appendSlice(gpa, "\\n"),
            '\r' => try out.appendSlice(gpa, "\\r"),
            '\t' => try out.appendSlice(gpa, "\\t"),
            else => {
                const raw = c < 0x20 or c >= 0x7f;
                if (raw) {
                    const esc = try std.fmt.allocPrint(gpa, "\\u{x:0>4}", .{c});
                    defer gpa.free(esc);
                    try out.appendSlice(gpa, esc);
                } else try out.append(gpa, c);
            },
        }
    }
    return out.toOwnedSlice(gpa);
}

pub fn jsonString(gpa: std.mem.Allocator, s: []const u8) ![]u8 {
    const escaped = try jsonEscape(gpa, s);
    defer gpa.free(escaped);
    return std.fmt.allocPrint(gpa, "\"{s}\"", .{escaped});
}

pub fn writeFile(io: std.Io, path: []const u8, data: []const u8) !void {
    const dir_name = std.fs.path.dirname(path) orelse ".";
    const base = std.fs.path.basename(path);
    var dir = try std.Io.Dir.openDirAbsolute(io, dir_name, .{});
    defer dir.close(io);
    try dir.writeFile(io, .{ .sub_path = base, .data = data });
}

/// Wall-clock seconds since the epoch (run ids and metadata only; never used
/// to decide anything).
pub fn unixSeconds() i64 {
    var ts: std.os.linux.timespec = undefined;
    _ = std.os.linux.clock_gettime(std.os.linux.CLOCK.REALTIME, &ts);
    return @as(i64, ts.sec);
}

pub fn monotonicNanos() i128 {
    var ts: std.os.linux.timespec = undefined;
    _ = std.os.linux.clock_gettime(std.os.linux.CLOCK.MONOTONIC, &ts);
    return @as(i128, ts.sec) * 1_000_000_000 + ts.nsec;
}

test "sha256 matches the known empty-string digest" {
    try std.testing.expectEqualStrings(
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        &sha256Hex(""),
    );
    try std.testing.expectEqualStrings(
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        &sha256Hex("abc"),
    );
}

test "json escaping protects quotes and control bytes" {
    const gpa = std.testing.allocator;
    const out = try jsonString(gpa, "a\"b\\c\nd");
    defer gpa.free(out);
    try std.testing.expectEqualStrings("\"a\\\"b\\\\c\\nd\"", out);
}
