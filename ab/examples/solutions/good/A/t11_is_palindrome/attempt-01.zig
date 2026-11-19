const std = @import("std");

pub fn isPalindrome(s: []const u8) bool {
    var i: usize = 0;
    var j: usize = s.len;
    while (i < j) {
        j -= 1;
        if (s[i] != s[j]) return false;
        i += 1;
    }
    return true;
}
