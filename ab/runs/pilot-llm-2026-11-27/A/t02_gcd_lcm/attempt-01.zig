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
    const g = gcd(a, b);
    return (a / g) * b;
}
