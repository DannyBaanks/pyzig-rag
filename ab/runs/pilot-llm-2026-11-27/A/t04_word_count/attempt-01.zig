pub fn wordCount(s: []const u8) usize {
    var count: usize = 0;
    var in_word = false;

    for (s) |c| {
        const is_space = c == ' ' or c == '\t' or c == '\n' or c == '\r' or c == '\x0b' or c == '\x0c';
        if (is_space) {
            in_word = false;
        } else if (!in_word) {
            in_word = true;
            count += 1;
        }
    }

    return count;
}
