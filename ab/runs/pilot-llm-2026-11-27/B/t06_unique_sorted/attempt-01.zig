const std = @import("std");

fn i32LessThan(_: void, a: i32, b: i32) bool {
    return a < b;
}

/// Devuelve los valores unicos de `xs` ordenados de menor a mayor.
/// El slice devuelto es propiedad del llamador (liberarlo con `allocator.free`).
pub fn uniqueSorted(allocator: std.mem.Allocator, xs: []const i32) ![]i32 {
    const out = try allocator.dupe(i32, xs);
    errdefer allocator.free(out);

    std.mem.sort(i32, out, {}, i32LessThan);
    if (out.len == 0) return out;

    var unique: usize = 1;
    for (out[1..]) |v| {
        if (v != out[unique - 1]) {
            out[unique] = v;
            unique += 1;
        }
    }

    return try allocator.realloc(out, unique);
}
