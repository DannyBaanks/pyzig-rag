const std = @import("std");

pub fn gcd(a: u64, b: u64) u64 {
    return missingGcdImpl(a, b);
}

pub fn lcm(a: u64, b: u64) u64 {
    return @divTrunc(a * b, gcd(a, b));
}
