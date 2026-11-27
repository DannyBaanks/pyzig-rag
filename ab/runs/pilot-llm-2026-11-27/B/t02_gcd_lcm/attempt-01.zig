const std = @import("std");

pub fn gcd(a: u64, b: u64) u64 {
    var x = a;
    var y = b;
    while (y != 0) {
        const r = x % y;
        x = y;
        y = r;
    }
    return x;
}

pub fn lcm(a: u64, b: u64) u64 {
    if (a == 0 or b == 0) return 0;
    const d = gcd(a, b);
    const product: u128 = @as(u128, a / d) * @as(u128, b);
    return @truncate(product);
}
