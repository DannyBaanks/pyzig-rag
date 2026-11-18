// F2 — pipeline de ejemplos equivalentes.
//
// `results.jsonl` guarda solo hallazgos; para que el assembler pueda admitir
// ejemplos nuevos necesitamos tambien los casos donde ambos lados coincidieron.
// Este modulo recolecta un numero acotado de EQUIV (determinista: los primeros
// del stream con ese seed), los escribe como `equiv.jsonl` y sella un
// `harvest.json` con el seed, los campos comparados y los hashes de la
// ejecucion. El assembler Python verifica ese hash antes de tocar el corpus.
const std = @import("std");
const proto = @import("proto.zig");
const evidence = @import("evidence.zig");

pub const Meta = struct {
    op: []const u8,
    schema: []const u8,
    seed: u64,
    iterations: u64,
    fields: []const u8,
    subject_sha256: []const u8,
    results_sha256: *const [64]u8,
};

pub const Harvester = struct {
    gpa: std.mem.Allocator,
    limit: usize,
    lines: std.ArrayList(u8) = .empty,
    stored: usize = 0,
    total: u64 = 0,

    pub fn init(gpa: std.mem.Allocator, limit: usize) Harvester {
        return .{ .gpa = gpa, .limit = limit };
    }

    pub fn deinit(self: *Harvester) void {
        self.lines.deinit(self.gpa);
    }

    /// Guarda un caso EQUIV mientras haya espacio; siempre cuenta el total.
    pub fn add(self: *Harvester, index: usize, case: []const u8, obs: proto.Obs) !void {
        self.total += 1;
        if (self.stored >= self.limit) return;

        const case_hex = try proto.hexEncode(self.gpa, case);
        defer self.gpa.free(case_hex);
        const obs_hex = try proto.hexEncode(self.gpa, obs.payload);
        defer self.gpa.free(obs_hex);
        const case_sha = evidence.sha256Hex(case);
        const obs_sha = evidence.sha256Hex(obs.payload);

        try self.lines.print(self.gpa,
            "{{\"i\":{d},\"case_sha256\":\"{s}\",\"case\":\"{s}\",\"status\":\"{s}\",\"obs_sha256\":\"{s}\",\"obs\":\"{s}\"}}\n",
            .{ index, &case_sha, case_hex, obs.status.name(), &obs_sha, obs_hex },
        );
        self.stored += 1;
    }

    /// Escribe `equiv.jsonl` y `harvest.json` dentro de run_dir.
    pub fn write(self: *const Harvester, io: std.Io, run_dir: []const u8, meta: Meta) !void {
        const equiv_path = try std.fs.path.join(self.gpa, &.{ run_dir, "equiv.jsonl" });
        defer self.gpa.free(equiv_path);
        const harvest_path = try std.fs.path.join(self.gpa, &.{ run_dir, "harvest.json" });
        defer self.gpa.free(harvest_path);

        const equiv_sha = evidence.sha256Hex(self.lines.items);
        try evidence.writeFile(io, equiv_path, self.lines.items);

        const op = try evidence.jsonString(self.gpa, meta.op);
        defer self.gpa.free(op);
        const schema = try evidence.jsonString(self.gpa, meta.schema);
        defer self.gpa.free(schema);
        const fields = try evidence.jsonString(self.gpa, meta.fields);
        defer self.gpa.free(fields);
        const subject_sha = try evidence.jsonString(self.gpa, meta.subject_sha256);
        defer self.gpa.free(subject_sha);

        const doc = try std.fmt.allocPrint(self.gpa,
            \\{{
            \\  "kind": "fuzz-harvest-v1",
            \\  "op": {s},
            \\  "schema": {s},
            \\  "fields": {s},
            \\  "seed": {d},
            \\  "iterations": {d},
            \\  "subject_sha256": {s},
            \\  "results_sha256": "{s}",
            \\  "equiv_total": {d},
            \\  "equiv_stored": {d},
            \\  "equiv_sha256": "{s}",
            \\  "equiv_file": "equiv.jsonl"
            \\}}
            \\
        , .{
            op, schema, fields, meta.seed, meta.iterations, subject_sha,
            meta.results_sha256, self.total, self.stored, &equiv_sha,
        });
        defer self.gpa.free(doc);
        try evidence.writeFile(io, harvest_path, doc);
    }
};
