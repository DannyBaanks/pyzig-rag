// pyzig-fuzz — differential fuzzing engine for pyzig-rag.
//
// The engine is the hot path: it generates cases, drives the Zig subject and
// the Python oracle as batched processes, classifies every pair and persists
// hashed evidence. Neither side is executed once per case: a chunk of cases
// is one process on each side.
const std = @import("std");
const proto = @import("proto.zig");
const gen = @import("gen.zig");
const rngmod = @import("rng.zig");
const runner = @import("runner.zig");
const compare = @import("compare.zig");
const evidence = @import("evidence.zig");
const pipeline = @import("pipeline.zig");

pub const VERSION = "0.1.0";

const Config = struct {
    op: []const u8 = "unknown",
    schema: gen.Schema = .argv,
    seed: u64 = 1337,
    iterations: u64 = 1000,
    chunk: usize = 500,
    replay: usize = 16,
    harvest_limit: usize = 200,
    timeout_ms: u64 = 60_000,
    subject: []const u8 = "",
    python: []const u8 = "/usr/bin/python3",
    repo: []const u8 = "",
    workdir: []const u8 = "",
    run_dir: []const u8 = "",
    out: []const u8 = "",
    fields: []const u8 = "",
    sandbox: runner.SandboxMode = .auto,
    allow_unsandboxed: bool = false,
    json: bool = false,
};

fn usage(io: std.Io) void {
    const msg =
        \\pyzig-fuzz — differential fuzzer for pyzig-rag (Zig engine)
        \\
        \\Usage:
        \\  pyzig-fuzz doctor [--json]
        \\  pyzig-fuzz gen --schema <s> --seed <n> --iterations <n> --out <file>
        \\  pyzig-fuzz diff --op <id> --schema <s> --fields <a,b,c>
        \\                  --seed <n> --iterations <n>
        \\                  --subject <bin> --repo <dir> [--python <bin>]
        \\                  --workdir <dir> --run-dir <dir>
        \\                  [--chunk <n>] [--replay <n>] [--harvest-limit <n>] [--timeout-ms <n>]
        \\                  [--sandbox auto|bwrap|none] [--allow-unsandboxed] [--json]
        \\  pyzig-fuzz assemble --corpus <file> --ops <op1,op2,...> --out <file>
        \\  pyzig-fuzz harvest --run-dir <dir> --out <candidates.jsonl> [--schema <s>]
        \\
        \\Schemas: argv, kv, read, write, exists, splitfmt, sleep, env, spawn, stdout, sha256, base64, hex, parseint, divmod, bits, packint, straffix, parsefloat, sortkey, intbytes, roundfloat, utf8cp, pipe
        \\
    ;
    std.Io.File.stdout().writeStreamingAll(io, msg) catch {};
}



fn printOut(io: std.Io, comptime fmt: []const u8, args: anytype) void {
    var buf: [4096]u8 = undefined;
    var w = std.Io.File.stdout().writer(io, &buf);
    w.interface.print(fmt, args) catch return;
    w.interface.flush() catch return;
}

fn cmdDoctor(gpa: std.mem.Allocator, io: std.Io, cfg: Config, path_env: ?[]const u8) !u8 {
    const p = try runner.probe(gpa, io, path_env);
    defer p.deinit(gpa);
    if (cfg.json) {
        printOut(io, "{{\"bwrap\":\"{s}\",\"bwrap_usable\":{s},\"prlimit\":\"{s}\",\"note\":\"{s}\"}}\n", .{
            p.bwrap orelse "",
            if (p.bwrap_usable) "true" else "false",
            p.prlimit orelse "",
            p.note,
        });
    } else {
        printOut(io, "bwrap:        {s} (usable: {s})\n", .{ p.bwrap orelse "no", if (p.bwrap_usable) "si" else "no" });
        printOut(io, "prlimit:      {s}\n", .{p.prlimit orelse "no"});
        printOut(io, "nota:         {s}\n", .{p.note});
        printOut(io, "sandbox:      {s}\n", .{if (p.bwrap_usable) "fail-closed con bwrap disponible" else "fail-closed: sin bwrap, hace falta --allow-unsandboxed"});
    }
    return 0;
}

fn cmdGen(gpa: std.mem.Allocator, io: std.Io, cfg: Config) !u8 {
    if (cfg.out.len == 0) {
        std.debug.print("falta --out\n", .{});
        return 2;
    }
    var r = rngmod.Rng.fork(cfg.seed, cfg.schema.name());
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(gpa);
    var i: u64 = 0;
    while (i < cfg.iterations) : (i += 1) {
        const payload = try gen.generate(gpa, cfg.schema, &r);
        defer gpa.free(payload);
        const hex = try proto.hexEncode(gpa, payload);
        defer gpa.free(hex);
        try out.appendSlice(gpa, hex);
        try out.append(gpa, '\n');
    }
    try evidence.writeFile(io, cfg.out, out.items);
    printOut(io, "generadas {d} casos ({s}) -> {s}\n", .{ cfg.iterations, cfg.schema.name(), cfg.out });
    return 0;
}

const Chunk = struct {
    payloads: std.ArrayList([]u8),
    hexes: std.ArrayList([]const u8),

    fn deinit(self: *Chunk, gpa: std.mem.Allocator) void {
        for (self.payloads.items) |p| gpa.free(p);
        for (self.hexes.items) |h| gpa.free(h);
        self.payloads.deinit(gpa);
        self.hexes.deinit(gpa);
    }
};

fn buildChunk(gpa: std.mem.Allocator, cfg: Config, r: *rngmod.Rng, n: usize) !Chunk {
    var chunk = Chunk{ .payloads = .empty, .hexes = .empty };
    errdefer chunk.deinit(gpa);
    var i: usize = 0;
    while (i < n) : (i += 1) {
        const payload = try gen.generate(gpa, cfg.schema, r);
        errdefer gpa.free(payload);
        const hex = try proto.hexEncode(gpa, payload);
        errdefer gpa.free(hex);
        try chunk.payloads.append(gpa, payload);
        try chunk.hexes.append(gpa, hex);
    }
    return chunk;
}

fn writeCases(gpa: std.mem.Allocator, io: std.Io, path: []const u8, chunk: *const Chunk, from: usize, to: usize) !void {
    var buf: std.ArrayList(u8) = .empty;
    defer buf.deinit(gpa);
    var i = from;
    while (i < to) : (i += 1) {
        try buf.appendSlice(gpa, chunk.hexes.items[i]);
        try buf.append(gpa, '\n');
    }
    try evidence.writeFile(io, path, buf.items);
}

fn runSubject(gpa: std.mem.Allocator, io: std.Io, p: runner.Probe, cfg: Config, cases_rel: []const u8, obs_rel: []const u8) !runner.Outcome {
    const args = [_][]const u8{ cases_rel, obs_rel };
    const binds = [_][2][]const u8{.{ cfg.subject, "/subject" }};
    return runner.runBatch(gpa, io, p, .{
        .sandbox = cfg.sandbox,
        .allow_unsandboxed = cfg.allow_unsandboxed,
        .workdir = cfg.workdir,
        .timeout_ms = cfg.timeout_ms,
    }, .{
        .program = "/subject",
        .args = &args,
        .ro_binds = &binds,
    });
}

fn runOracle(gpa: std.mem.Allocator, io: std.Io, p: runner.Probe, cfg: Config, cases_rel: []const u8, obs_rel: []const u8) !runner.Outcome {
    const args = [_][]const u8{ "-m", "pyzig.fuzz.oracle", "--schema", cfg.schema.name(), "--cases", cases_rel, "--obs", obs_rel };
    const binds = [_][2][]const u8{.{ cfg.repo, "/repo" }};
    const env = [_][2][]const u8{.{ "PYTHONPATH", "/repo" }};
    return runner.runBatch(gpa, io, p, .{
        .sandbox = cfg.sandbox,
        .allow_unsandboxed = cfg.allow_unsandboxed,
        .workdir = cfg.workdir,
        .timeout_ms = cfg.timeout_ms,
    }, .{
        .program = cfg.python,
        .args = &args,
        .ro_binds = &binds,
        .env = &env,
    });
}

fn absPath(gpa: std.mem.Allocator, io: std.Io, path: []const u8) ![]const u8 {
    if (path.len > 0 and path[0] == '/') return gpa.dupe(u8, path);
    const cwd = try std.process.currentPathAlloc(io, gpa);
    defer gpa.free(cwd);
    return std.fs.path.join(gpa, &.{ cwd, path });
}

/// Never compare against observations left by an earlier chunk or run.
/// A stale obs file is a silent false result; absence of a file is fine.
fn clearObs(io: std.Io, paths: []const []const u8) !void {
    for (paths) |path| {
        std.Io.Dir.deleteFileAbsolute(io, path) catch |err| switch (err) {
            error.FileNotFound => {},
            else => return err,
        };
    }
}

/// Find the first case that kills the subject on its own. Returns null when
/// no single case reproduces the failure (an interaction between cases).
fn localizeFailure(gpa: std.mem.Allocator, io: std.Io, p: runner.Probe, cfg: Config, chunk: *const Chunk, from: usize, to: usize, cases_path: []const u8, single_obs_path: []const u8) !?usize {
    var i = from;
    while (i < to) : (i += 1) {
        try clearObs(io, &.{single_obs_path});
        try writeCases(gpa, io, cases_path, chunk, i, i + 1);
        const out = try runSubject(gpa, io, p, cfg, "cases.hexl", "single.zigl");
        if (out.timed_out or out.signal != null or (out.exit_code != null and out.exit_code.? != 0)) {
            return i;
        }
    }
    return null;
}

fn splitCsv(gpa: std.mem.Allocator, csv: []const u8) ![][]const u8 {
    var out: std.ArrayList([]const u8) = .empty;
    errdefer out.deinit(gpa);
    var it = std.mem.splitScalar(u8, csv, ',');
    while (it.next()) |part| {
        const t = std.mem.trim(u8, part, " \t");
        if (t.len > 0) try out.append(gpa, t);
    }
    return out.toOwnedSlice(gpa);
}

fn cmdDiff(gpa: std.mem.Allocator, io: std.Io, cfg: Config, path_env: ?[]const u8) !u8 {
    if (cfg.subject.len == 0 or cfg.repo.len == 0 or cfg.workdir.len == 0 or cfg.run_dir.len == 0) {
        std.debug.print("diff necesita --subject --repo --workdir --run-dir\n", .{});
        return 2;
    }
    if (cfg.fields.len == 0) {
        std.debug.print("diff necesita --fields (contrato del corpus: campos comparados)\n", .{});
        return 2;
    }

    const p = try runner.probe(gpa, io, path_env);
    defer p.deinit(gpa);
    const sandbox_label = if (p.bwrap_usable) "bwrap" else "none";
    if (!p.bwrap_usable and !cfg.allow_unsandboxed) {
        std.debug.print("sandbox no disponible ({s}); reintenta con --allow-unsandboxed\n", .{p.note});
        return 2;
    }

    const fields = try splitCsv(gpa, cfg.fields);
    defer gpa.free(fields);

    const workdir = try absPath(gpa, io, cfg.workdir);
    defer gpa.free(workdir);
    const run_dir = try absPath(gpa, io, cfg.run_dir);
    defer gpa.free(run_dir);

    std.Io.Dir.cwd().createDirPath(io, workdir) catch {};
    std.Io.Dir.cwd().createDirPath(io, run_dir) catch {};

    const cases_path = try std.fs.path.join(gpa, &.{ workdir, "cases.hexl" });
    defer gpa.free(cases_path);
    const oracle_obs_path = try std.fs.path.join(gpa, &.{ workdir, "oracle.zigl" });
    defer gpa.free(oracle_obs_path);
    const subject_obs_path = try std.fs.path.join(gpa, &.{ workdir, "subject.zigl" });
    defer gpa.free(subject_obs_path);
    const replay_cases_path = try std.fs.path.join(gpa, &.{ workdir, "replay.hexl" });
    defer gpa.free(replay_cases_path);
    const replay_obs_path = try std.fs.path.join(gpa, &.{ workdir, "replay.zigl" });
    defer gpa.free(replay_obs_path);
    const single_obs_path = try std.fs.path.join(gpa, &.{ workdir, "single.zigl" });
    defer gpa.free(single_obs_path);

    const started = evidence.monotonicNanos();
    var r = rngmod.Rng.fork(cfg.seed, cfg.op);

    var counts = [_]u64{0} ** @typeInfo(compare.Class).@"enum".fields.len;
    var results: std.ArrayList(u8) = .empty;
    defer results.deinit(gpa);
    var harvest = pipeline.Harvester.init(gpa, cfg.harvest_limit);
    defer harvest.deinit();
    var divergences: u64 = 0;
    var generated: u64 = 0;

    while (generated < cfg.iterations) {
        const remaining = cfg.iterations - generated;
        const n: usize = @intCast(@min(remaining, @as(u64, @intCast(cfg.chunk))));
        var chunk = try buildChunk(gpa, cfg, &r, n);
        defer chunk.deinit(gpa);

        try clearObs(io, &.{ oracle_obs_path, subject_obs_path, replay_obs_path, single_obs_path });
        try writeCases(gpa, io, cases_path, &chunk, 0, n);

        const oracle_out = try runOracle(gpa, io, p, cfg, "cases.hexl", "oracle.zigl");
        const subject_out = try runSubject(gpa, io, p, cfg, "cases.hexl", "subject.zigl");

        if (oracle_out.spawn_failed) {
            std.debug.print("oracle no arranco: {s}\n", .{oracle_out.stderr});
            return 2;
        }
        if (subject_out.spawn_failed) {
            std.debug.print("subject no arranco: {s}\n", .{subject_out.stderr});
            return 2;
        }
        // Fallo visible: un lado que sale con codigo != 0 sin observaciones
        // es un fallo del arnes, no una divergencia silenciosa.
        if (oracle_out.exit_code == null or oracle_out.exit_code.? != 0) {
            std.debug.print("oracle fallo (exit={?}, timeout={}): {s}\n", .{
                oracle_out.exit_code, oracle_out.timed_out, oracle_out.stderr,
            });
            return 2;
        }
        if (subject_out.exit_code == null or subject_out.exit_code.? != 0) {
            std.debug.print("subject fallo (exit={?}, timeout={}): {s}\n", .{
                subject_out.exit_code, subject_out.timed_out, subject_out.stderr,
            });
        }

        const oracle_bytes = (try evidence.readFileAbs(io, gpa, oracle_obs_path, 64 * 1024 * 1024)) orelse "";
        defer gpa.free(oracle_bytes);
        const subject_bytes = (try evidence.readFileAbs(io, gpa, subject_obs_path, 64 * 1024 * 1024)) orelse "";
        defer gpa.free(subject_bytes);

        const oracle_lines = try proto.splitLines(oracle_bytes, gpa);
        defer gpa.free(oracle_lines);
        const subject_lines = try proto.splitLines(subject_bytes, gpa);
        defer gpa.free(subject_lines);

        var i: usize = 0;
        while (i < n) : (i += 1) {
            var subject_obs: ?proto.Obs = null;
            var oracle_obs: ?proto.Obs = null;
            if (i < subject_lines.len) {
                subject_obs = proto.parseObsLine(gpa, subject_lines[i]) catch null;
            }
            if (i < oracle_lines.len) {
                oracle_obs = proto.parseObsLine(gpa, oracle_lines[i]) catch null;
            }
            const d = try compare.classifyFields(gpa, fields, subject_obs, oracle_obs);
            defer d.deinit(gpa);
            counts[@intFromEnum(d.class)] += 1;
            if (d.class == .EQUIV) {
                if (subject_obs) |o| try harvest.add(i, chunk.payloads.items[i], o);
            }
            if (d.class.isDivergence()) {
                divergences += 1;
                try appendResult(gpa, &results, i, d, chunk.payloads.items[i], subject_obs, oracle_obs);
            }
            if (subject_obs) |o| proto.freeObs(gpa, o);
            if (oracle_obs) |o| proto.freeObs(gpa, o);
        }

        // A subject that died mid-chunk leaves observations missing: localize
        // the first failing case by re-running single cases.
        if (subject_out.exit_code == null or subject_out.signal != null or subject_out.timed_out) {
            if (subject_lines.len < n) {
                const culprit = try localizeFailure(gpa, io, p, cfg, &chunk, subject_lines.len, n, cases_path, single_obs_path);
                if (culprit) |idx| {
                    counts[@intFromEnum(compare.Class.CRASH)] += 1;
                    divergences += 1;
                    try appendCrash(gpa, &results, idx, chunk.payloads.items[idx]);
                } else {
                    counts[@intFromEnum(compare.Class.INCONCLUSIVE)] += @intCast(n - subject_lines.len);
                }
            }
        }

        // Replay a sample of the chunk: the same input must give the same answer.
        if (cfg.replay > 0 and n > 0) {
            const sample = @min(cfg.replay, n);
            try clearObs(io, &.{replay_obs_path});
            try writeCases(gpa, io, replay_cases_path, &chunk, 0, sample);
            _ = try runSubject(gpa, io, p, cfg, "replay.hexl", "replay.zigl");
            const replay_bytes = (try evidence.readFileAbs(io, gpa, replay_obs_path, 64 * 1024 * 1024)) orelse "";
            defer gpa.free(replay_bytes);
            const replay_lines = try proto.splitLines(replay_bytes, gpa);
            defer gpa.free(replay_lines);
            var j: usize = 0;
            while (j < sample) : (j += 1) {
                if (j >= replay_lines.len or j >= subject_lines.len) continue;
                const a = proto.parseObsLine(gpa, subject_lines[j]) catch continue;
                defer proto.freeObs(gpa, a);
                const b = proto.parseObsLine(gpa, replay_lines[j]) catch continue;
                defer proto.freeObs(gpa, b);
                if (!compare.isStable(a, b)) {
                    counts[@intFromEnum(compare.Class.NONDETERMINISTIC)] += 1;
                    divergences += 1;
                    try appendUnstable(gpa, &results, j, chunk.payloads.items[j]);
                }
            }
        }

        generated += n;
    }

    const elapsed_ns = evidence.monotonicNanos() - started;
    const elapsed_ms: f64 = @as(f64, @floatFromInt(elapsed_ns)) / 1_000_000.0;
    const ops_per_sec: f64 = if (elapsed_ms > 0)
        @as(f64, @floatFromInt(generated)) / (elapsed_ms / 1000.0)
    else
        0;

    const results_sha = evidence.sha256Hex(results.items);
    try writeRunEvidence(gpa, io, cfg, run_dir, p, sandbox_label, counts, divergences, generated, elapsed_ms, ops_per_sec, results_sha, results.items);

    const harvest_subject_sha = (try evidence.sha256File(io, gpa, cfg.subject)) orelse "";
    defer gpa.free(harvest_subject_sha);
    try harvest.write(io, run_dir, .{
        .op = cfg.op,
        .schema = cfg.schema.name(),
        .seed = cfg.seed,
        .iterations = generated,
        .fields = cfg.fields,
        .subject_sha256 = harvest_subject_sha,
        .results_sha256 = &results_sha,
    });

    if (cfg.json) {
        printOut(io, "{{\"op\":\"{s}\",\"schema\":\"{s}\",\"cases\":{d},\"divergences\":{d},\"sandbox\":\"{s}\",\"ops_per_sec\":{d:.1},\"results_sha256\":\"{s}\"}}\n", .{
            cfg.op, cfg.schema.name(), generated, divergences, sandbox_label, ops_per_sec, results_sha,
        });
    } else {
        printOut(io, "op={s} schema={s} casos={d} divergencias={d} sandbox={s} ops/s={d:.0}\n", .{
            cfg.op, cfg.schema.name(), generated, divergences, sandbox_label, ops_per_sec,
        });
        inline for (@typeInfo(compare.Class).@"enum".fields) |f| {
            printOut(io, "  {s}: {d}\n", .{ f.name, counts[@intFromEnum(@field(compare.Class, f.name))] });
        }
        printOut(io, "evidencia: {s}/results.jsonl\n", .{run_dir});
    }

    return if (divergences > 0) 1 else 0;
}

fn appendResult(gpa: std.mem.Allocator, results: *std.ArrayList(u8), index: usize, d: compare.Diff, payload: []const u8, subject: ?proto.Obs, oracle: ?proto.Obs) !void {
    const case_hex = try proto.hexEncode(gpa, payload);
    defer gpa.free(case_hex);
    const case_sha = evidence.sha256Hex(payload);
    const subject_hex = if (subject) |o| try proto.hexEncode(gpa, o.payload) else try gpa.dupe(u8, "");
    defer gpa.free(subject_hex);
    const oracle_hex = if (oracle) |o| try proto.hexEncode(gpa, o.payload) else try gpa.dupe(u8, "");
    defer gpa.free(oracle_hex);
    const subject_status = if (subject) |o| o.status.name() else "missing";
    const oracle_status = if (oracle) |o| o.status.name() else "missing";

    var buf: std.ArrayList(u8) = .empty;
    defer buf.deinit(gpa);

    try buf.print(gpa, "{{", .{});
    try buf.print(gpa, "\"i\":{d},", .{index});
    try buf.print(gpa, "\"class\":\"{s}\",", .{d.class.name()});
    try buf.print(gpa, "\"case_sha256\":\"{s}\",", .{case_sha});
    try buf.print(gpa, "\"case\":\"{s}\",", .{case_hex});
    try buf.print(gpa, "\"fields\":[", .{});
    for (d.field_diffs, 0..) |fd, k| {
        if (k > 0) try buf.appendSlice(gpa, ",");
        // Los valores vienen de datos del caso: pueden traer comillas,
        // saltos de linea o bytes no imprimibles -> hay que escaparlos, si no
        // results.jsonl deja de ser JSON valido.
        const name_j = try evidence.jsonString(gpa, fd.name);
        const subj_j = try evidence.jsonString(gpa, fd.subject);
        const orac_j = try evidence.jsonString(gpa, fd.oracle);
        try buf.print(gpa, "{{\"name\":{s},\"subject\":{s},\"oracle\":{s}}}", .{
            name_j, subj_j, orac_j,
        });
        // Se liberan tras escribir: en el camino de error el proceso muere
        // igual, y meter `defer` aqui acumularia liberaciones hasta el final
        // de la funcion.
        gpa.free(name_j);
        gpa.free(subj_j);
        gpa.free(orac_j);
    }
    try buf.print(gpa, "],", .{});
    try buf.print(gpa, "\"subject\":{{", .{});
    try buf.print(gpa, "\"status\":\"{s}\",", .{subject_status});
    try buf.print(gpa, "\"payload\":\"{s}\"", .{subject_hex});
    try buf.print(gpa, "}},", .{});
    try buf.print(gpa, "\"oracle\":{{", .{});
    try buf.print(gpa, "\"status\":\"{s}\",", .{oracle_status});
    try buf.print(gpa, "\"payload\":\"{s}\"", .{oracle_hex});
    try buf.print(gpa, "}}", .{});
    // Cierre del REGISTRO: el `}}` de arriba cierra el objeto "oracle"; sin
    // este segundo, results.jsonl quedaba con JSON truncado (y el hash de
    // evidencia registraba un fichero ilegible para cualquier parser).
    try buf.print(gpa, "}}\n", .{});
    try results.appendSlice(gpa, buf.items);
}

fn appendCrash(gpa: std.mem.Allocator, results: *std.ArrayList(u8), index: usize, payload: []const u8) !void {
    const case_hex = try proto.hexEncode(gpa, payload);
    defer gpa.free(case_hex);
    const case_sha = evidence.sha256Hex(payload);

    var buf: std.ArrayList(u8) = .empty;
    defer buf.deinit(gpa);

    try buf.print(gpa, "{{", .{});
    try buf.print(gpa, "\"i\":{d},", .{index});
    try buf.print(gpa, "\"class\":\"CRASH\",", .{});
    try buf.print(gpa, "\"case_sha256\":\"{s}\",", .{case_sha});
    try buf.print(gpa, "\"case\":\"{s}\"", .{case_hex});
    try buf.print(gpa, "}}\n", .{});
    try results.appendSlice(gpa, buf.items);
}

fn appendUnstable(gpa: std.mem.Allocator, results: *std.ArrayList(u8), index: usize, payload: []const u8) !void {
    const case_hex = try proto.hexEncode(gpa, payload);
    defer gpa.free(case_hex);
    const case_sha = evidence.sha256Hex(payload);

    var buf: std.ArrayList(u8) = .empty;
    defer buf.deinit(gpa);

    try buf.print(gpa, "{{", .{});
    try buf.print(gpa, "\"i\":{d},", .{index});
    try buf.print(gpa, "\"class\":\"NONDETERMINISTIC\",", .{});
    try buf.print(gpa, "\"case_sha256\":\"{s}\",", .{case_sha});
    try buf.print(gpa, "\"case\":\"{s}\"", .{case_hex});
    try buf.print(gpa, "}}\n", .{});
    try results.appendSlice(gpa, buf.items);
}

fn writeRunEvidence(
    gpa: std.mem.Allocator,
    io: std.Io,
    cfg: Config,
    run_dir: []const u8,
    p: runner.Probe,
    sandbox_label: []const u8,
    counts: [@typeInfo(compare.Class).@"enum".fields.len]u64,
    divergences: u64,
    cases: u64,
    elapsed_ms: f64,
    ops_per_sec: f64,
    results_sha: [64]u8,
    results_bytes: []const u8,
) !void {
    const meta_path = try std.fs.path.join(gpa, &.{ run_dir, "meta.json" });
    defer gpa.free(meta_path);
    const results_path = try std.fs.path.join(gpa, &.{ run_dir, "results.jsonl" });
    defer gpa.free(results_path);
    const summary_path = try std.fs.path.join(gpa, &.{ run_dir, "summary.json" });
    defer gpa.free(summary_path);

    const subject_sha = (try evidence.sha256File(io, gpa, cfg.subject)) orelse "";

    const meta = try std.fmt.allocPrint(gpa,
        \\{{
        \\  "engine": "pyzig-fuzz",
        \\  "engine_version": "{s}",
        \\  "op": "{s}",
        \\  "schema": "{s}",
        \\  "fields": "{s}",
        \\  "seed": {d},
        \\  "iterations": {d},
        \\  "chunk": {d},
        \\  "replay": {d},
        \\  "timeout_ms": {d},
        \\  "sandbox": "{s}",
        \\  "bwrap_usable": {s},
        \\  "prlimit": "{s}",
        \\  "allow_unsandboxed": {s},
        \\  "workdir": "{s}",
        \\  "subject": "{s}",
        \\  "subject_sha256": "{s}",
        \\  "repo": "{s}",
        \\  "python": "{s}",
        \\  "zig_version": "{s}",
        \\  "started_at": {d}
        \\}}
        \\
    , .{
        VERSION,
        cfg.op,
        cfg.schema.name(),
        cfg.fields,
        cfg.seed,
        cfg.iterations,
        cfg.chunk,
        cfg.replay,
        cfg.timeout_ms,
        sandbox_label,
        if (p.bwrap_usable) "true" else "false",
        p.prlimit orelse "",
        if (cfg.allow_unsandboxed) "true" else "false",
        cfg.workdir,
        cfg.subject,
        subject_sha,
        cfg.repo,
        cfg.python,
        @import("builtin").zig_version_string,
        evidence.unixSeconds(),
    });
    defer gpa.free(meta);
    try evidence.writeFile(io, meta_path, meta);
    try evidence.writeFile(io, results_path, results_bytes);

    var count_json: std.ArrayList(u8) = .empty;
    defer count_json.deinit(gpa);
    try count_json.appendSlice(gpa, "{");
    inline for (@typeInfo(compare.Class).@"enum".fields, 0..) |f, k| {
        if (k > 0) try count_json.appendSlice(gpa, ",");
        try count_json.print(gpa, "\"{s}\":{d}", .{ f.name, counts[@intFromEnum(@field(compare.Class, f.name))] });
    }
    try count_json.appendSlice(gpa, "}");

    const summary = try std.fmt.allocPrint(gpa,
        \\{{
        \\  "op": "{s}",
        \\  "schema": "{s}",
        \\  "fields": "{s}",
        \\  "seed": {d},
        \\  "cases": {d},
        \\  "divergences": {d},
        \\  "counts": {s},
        \\  "sandbox": "{s}",
        \\  "elapsed_ms": {d:.2},
        \\  "ops_per_sec": {d:.1},
        \\  "results_sha256": "{s}",
        \\  "status": "{s}"
        \\}}
        \\
    , .{
        cfg.op,
        cfg.schema.name(),
        cfg.fields,
        cfg.seed,
        cases,
        divergences,
        count_json.items,
        sandbox_label,
        elapsed_ms,
        ops_per_sec,
        results_sha,
        if (divergences > 0) "DIVERGENCES_FOUND" else "CLEAN",
    });
    defer gpa.free(summary);
    try evidence.writeFile(io, summary_path, summary);
}

pub fn main(init: std.process.Init) !void {
    const gpa = init.gpa;
    const io = init.io;
    const args = init.minimal.args.vector;
    if (args.len < 2) {
        usage(io);
        return;
    }

    var cfg = Config{};
    const cmd: []const u8 = std.mem.span(args[1]);

    var i: usize = 2;
    while (i < args.len) : (i += 1) {
        const arg = std.mem.span(args[i]);
        if (std.mem.eql(u8, arg, "--json")) {
            cfg.json = true;
        } else if (std.mem.eql(u8, arg, "--allow-unsandboxed")) {
            cfg.allow_unsandboxed = true;
        } else if (std.mem.eql(u8, arg, "--help") or std.mem.eql(u8, arg, "-h")) {
            usage(io);
            return;
        } else if (i + 1 < args.len) {
            i += 1;
            const value = std.mem.span(args[i]);
            if (std.mem.eql(u8, arg, "--op")) {
                cfg.op = value;
            } else if (std.mem.eql(u8, arg, "--schema")) {
                cfg.schema = gen.Schema.fromName(value) orelse {
                    std.debug.print("schema desconocido: {s}\n", .{value});
                    std.process.exit(2);
                };
            } else if (std.mem.eql(u8, arg, "--seed")) {
                cfg.seed = std.fmt.parseInt(u64, value, 10) catch 1337;
            } else if (std.mem.eql(u8, arg, "--iterations")) {
                cfg.iterations = std.fmt.parseInt(u64, value, 10) catch 1000;
            } else if (std.mem.eql(u8, arg, "--chunk")) {
                cfg.chunk = std.fmt.parseInt(usize, value, 10) catch 500;
            } else if (std.mem.eql(u8, arg, "--replay")) {
                cfg.replay = std.fmt.parseInt(usize, value, 10) catch 0;
            } else if (std.mem.eql(u8, arg, "--harvest-limit")) {
                cfg.harvest_limit = std.fmt.parseInt(usize, value, 10) catch 200;
            } else if (std.mem.eql(u8, arg, "--fields")) {
                cfg.fields = value;
            } else if (std.mem.eql(u8, arg, "--timeout-ms")) {
                cfg.timeout_ms = std.fmt.parseInt(u64, value, 10) catch 60_000;
            } else if (std.mem.eql(u8, arg, "--subject")) {
                cfg.subject = value;
            } else if (std.mem.eql(u8, arg, "--python")) {
                cfg.python = value;
            } else if (std.mem.eql(u8, arg, "--repo")) {
                cfg.repo = value;
            } else if (std.mem.eql(u8, arg, "--workdir")) {
                cfg.workdir = value;
            } else if (std.mem.eql(u8, arg, "--run-dir")) {
                cfg.run_dir = value;
            } else if (std.mem.eql(u8, arg, "--out")) {
                cfg.out = value;
            } else if (std.mem.eql(u8, arg, "--sandbox")) {
                if (std.mem.eql(u8, value, "auto")) {
                    cfg.sandbox = .auto;
                } else if (std.mem.eql(u8, value, "bwrap")) {
                    cfg.sandbox = .bwrap;
                } else if (std.mem.eql(u8, value, "none")) {
                    cfg.sandbox = .none;
                } else {
                    std.debug.print("sandbox desconocido: {s}\n", .{value});
                    std.process.exit(2);
                }
            }
        }
    }

    if (std.mem.eql(u8, cmd, "doctor")) {
        std.process.exit(try cmdDoctor(gpa, io, cfg, init.environ_map.get("PATH")));
    } else if (std.mem.eql(u8, cmd, "gen")) {
        std.process.exit(try cmdGen(gpa, io, cfg));
    } else if (std.mem.eql(u8, cmd, "diff")) {
        std.process.exit(try cmdDiff(gpa, io, cfg, init.environ_map.get("PATH")));
    } else {
        std.debug.print("comando desconocido: {s}\n", .{cmd});
        usage(io);
        std.process.exit(2);
    }
}

