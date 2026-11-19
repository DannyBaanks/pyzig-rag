const std = @import("std");

fn isSpace(c: u8) bool {
    return c == ' ' or c == '\t' or c == '\n' or c == '\r' or c == 0x0b or c == 0x0c;
}

pub fn collapseSpaces(allocator: std.mem.Allocator, s: []const u8) ![]u8 {
    var needed: usize = 0;
    var pending = true;
    for (s) |c| {
        if (isSpace(c)) {
            pending = true;
            continue;
        }
        if (pending and needed > 0) needed += 1;
        needed += 1;
        pending = false;
    }
    const out = try allocator.alloc(u8, needed);
    var w: usize = 0;
    pending = true;
    for (s) |c| {
        if (isSpace(c)) {
            pending = true;
            continue;
        }
        if (pending and w > 0) {
            out[w] = ' ';
            w += 1;
        }
        out[w] = c;
        w += 1;
        pending = false;
    }
    return out;
}
