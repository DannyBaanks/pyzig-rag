// Sandboxed batch execution.
//
// House rule (borrowed from the PITON differential fuzzer): execution is
// fail-closed. If bubblewrap is usable, every subject and every oracle runs
// inside an isolated namespace with no network, a read-only system view and a
// private writable workdir. If bubblewrap is NOT usable, the engine refuses to
// run unless the operator explicitly allows an unsandboxed run, and that
// decision is recorded in the evidence.
const std = @import("std");

pub const SandboxMode = enum {
    auto,
    bwrap,
    none,

    pub fn name(self: SandboxMode) []const u8 {
        return @tagName(self);
    }
};

pub const Probe = struct {
    bwrap: ?[]const u8 = null,
    prlimit: ?[]const u8 = null,
    bwrap_usable: bool = false,
    note: []const u8 = "",

    /// Free the paths resolved by `probe`. The probe owns them.
    pub fn deinit(self: Probe, gpa: std.mem.Allocator) void {
        if (self.bwrap) |b| gpa.free(b);
        if (self.prlimit) |p| gpa.free(p);
    }
};

/// Resolve a program name against PATH.
pub fn which(gpa: std.mem.Allocator, io: std.Io, path_env: ?[]const u8, name: []const u8) !?[]const u8 {
    const path = path_env orelse return null;
    var it = std.mem.splitScalar(u8, path, ':');
    while (it.next()) |dir| {
        if (dir.len == 0) continue;
        const candidate = try std.fs.path.join(gpa, &.{ dir, name });
        const found = std.Io.Dir.cwd().statFile(io, candidate, .{}) catch null;
        if (found == null) {
            gpa.free(candidate);
            continue;
        }
        return candidate;
    }
    return null;
}

/// Probe the isolation primitives available on this machine.
pub fn probe(gpa: std.mem.Allocator, io: std.Io, path_env: ?[]const u8) !Probe {
    var p = Probe{};
    p.bwrap = try which(gpa, io, path_env, "bwrap");
    p.prlimit = try which(gpa, io, path_env, "prlimit");

    if (p.bwrap) |bwrap| {
        const argv = [_][]const u8{
            bwrap,   "--unshare-all", "--die-with-parent", "--new-session",
            "--ro-bind", "/usr",      "/usr",
            "--ro-bind", "/lib",      "/lib",
            "--ro-bind", "/lib64",    "/lib64",
            "--proc",   "/proc",      "--dev",
            "/dev",    "--clearenv",  "/usr/bin/true",
        };
        const res = std.process.run(gpa, io, .{ .argv = &argv, .stdout_limit = .limited(4096), .stderr_limit = .limited(4096) }) catch {
            p.note = "bwrap presente pero no ejecutable";
            return p;
        };
        p.bwrap_usable = switch (res.term) {
            .exited => |code| code == 0,
            else => false,
        };
        if (!p.bwrap_usable) p.note = "bwrap no puede crear namespace de usuario aqui";
    } else {
        p.note = "bwrap no encontrado";
    }
    return p;
}

pub const RunOpts = struct {
    sandbox: SandboxMode = .auto,
    allow_unsandboxed: bool = false,
    workdir: []const u8,
    timeout_ms: u64 = 60_000,
    cpu_seconds: u64 = 30,
    fsize_bytes: u64 = 64 * 1024 * 1024,
};

pub const Outcome = struct {
    ran: bool = false,
    exit_code: ?u8 = null,
    signal: ?u32 = null,
    timed_out: bool = false,
    spawn_failed: bool = false,
    stdout: []const u8 = "",
    stderr: []const u8 = "",
    sandbox: []const u8 = "none",
};

pub const Payload = struct {
    /// Absolute path of the program to run (already inside the sandbox image).
    program: []const u8,
    /// Arguments passed to the program.
    args: []const []const u8 = &.{},
    /// Extra read-only binds: host path -> sandbox path.
    ro_binds: []const [2][]const u8 = &.{},
    /// Extra environment entries (host value, sandbox value).
    env: []const [2][]const u8 = &.{},
};

pub const Error = error{
    SandboxUnavailable,
} || std.mem.Allocator.Error;

/// Run one batch program under the configured isolation.
pub fn runBatch(gpa: std.mem.Allocator, io: std.Io, p: Probe, opts: RunOpts, payload: Payload) !Outcome {
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(gpa);

    const use_bwrap = switch (opts.sandbox) {
        .bwrap => true,
        .none => false,
        .auto => p.bwrap_usable,
    };

    if (use_bwrap and !p.bwrap_usable) return error.SandboxUnavailable;
    if (!use_bwrap and !opts.allow_unsandboxed) return error.SandboxUnavailable;

    if (p.prlimit) |pr| {
        // Buffers de pila: su vida llega hasta el final de la funcion, asi
        // que el argv no puede quedar apuntando a memoria liberada.
        var cpu_buf: [32]u8 = undefined;
        var fsize_buf: [32]u8 = undefined;
        const cpu = try std.fmt.bufPrint(&cpu_buf, "--cpu={d}", .{opts.cpu_seconds});
        const fsize = try std.fmt.bufPrint(&fsize_buf, "--fsize={d}", .{opts.fsize_bytes});
        // RLIMIT_NPROC no se usa: es por usuario, no por proceso, y un limite
        // bajo hace fallar el fork que bwrap necesita para el namespace
        // ("Creating new namespace failed: Resource temporarily unavailable").
        try argv.appendSlice(gpa, &.{ pr, cpu, fsize, "--nofile=256", "--" });
    }

    if (use_bwrap) {
        const bwrap = p.bwrap.?;
        try argv.appendSlice(gpa, &.{
            bwrap,
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--ro-bind", "/usr",   "/usr",
            "--ro-bind", "/lib",   "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--proc",   "/proc",
            "--dev",    "/dev",
            "--tmpfs",  "/tmp",
            "--bind",   opts.workdir, "/work",
            "--chdir",  "/work",
            "--clearenv",
            "--setenv", "PATH", "/usr/bin:/bin",
            "--setenv", "HOME", "/tmp",
            "--setenv", "TMPDIR", "/tmp",
        });
        for (payload.ro_binds) |b| {
            try argv.appendSlice(gpa, &.{ "--ro-bind", b[0], b[1] });
        }
        for (payload.env) |e| {
            try argv.appendSlice(gpa, &.{ "--setenv", e[0], e[1] });
        }
        try argv.append(gpa, "--");
    }

    try argv.append(gpa, payload.program);
    try argv.appendSlice(gpa, payload.args);

    const res = std.process.run(gpa, io, .{
        .argv = argv.items,
        .cwd = .{ .path = opts.workdir },
        .stdout_limit = .limited(4 * 1024 * 1024),
        .stderr_limit = .limited(4 * 1024 * 1024),
        .timeout = .{ .duration = .{ .raw = std.Io.Duration.fromMilliseconds(@intCast(opts.timeout_ms)), .clock = .real } },
    }) catch |err| {
        if (err == error.Timeout) {
            return .{
                .ran = true,
                .timed_out = true,
                .sandbox = if (use_bwrap) "bwrap" else "none",
            };
        }
        return .{
            .spawn_failed = true,
            .stderr = @errorName(err),
            .sandbox = if (use_bwrap) "bwrap" else "none",
        };
    };

    var out = Outcome{ .ran = true, .sandbox = if (use_bwrap) "bwrap" else "none" };
    out.stdout = res.stdout;
    out.stderr = res.stderr;
    switch (res.term) {
        .exited => |code| out.exit_code = code,
        .signal => |sig| out.signal = @intFromEnum(sig),
        .stopped => |sig| out.signal = @intFromEnum(sig),
        .unknown => |code| out.signal = code,
    }
    return out;
}

test "which resolves an existing binary" {
    const gpa = std.testing.allocator;
    const found = try which(gpa, std.testing.io, "/usr/bin:/bin", "sh");
    try std.testing.expect(found != null);
    gpa.free(found.?);
    const missing = try which(gpa, std.testing.io, "/usr/bin:/bin", "definitely-not-here-xyz");
    try std.testing.expect(missing == null);
}
