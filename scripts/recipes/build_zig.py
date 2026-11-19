"""Recetas de BUILD de Zig 0.16.0 (operation_id `zig0.16/build-*`).

`py_ref` guarda el proyecto ROTO (build.zig + src/, tal cual falla en 0.16.0);
la entrada guarda el ARREGLO. `error_signatures` son lineas `error:` REALES copiadas
de `zig build` 0.16.0 sobre el proyecto roto (sin ruta ni posicion).

Cada entrada lleva `gate_mode: "build"` y `build_files` (el proyecto ARREGLADO):
el gate escribe ese proyecto en un directorio temporal y ejecuta `zig build test`
alli (sin red, sin dependencias). Ver pyzig/gates.py.
"""
from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"; PY = "3.12"
PROV = "zig 0.16.0 local (lib/std/Build); errores copiados de `zig build` 0.16.0; arreglo verificado con `zig build test`"
SRC = "zig-build"
_SKIP = dict(type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
             skip_reason="build de Zig: sin driver diferencial")


def _join(files):
    return "\n".join(f"// {p}\n{c.rstrip()}\n" for p, c in files.items())


def entry(oid, name, intent, aliases, broken, fixed, test_path, sigs, apis, constraints,
          differences, error_behavior="", side_effects=None, ownership=""):
    return dict(
        operation_id=oid, name=name, intent=intent, aliases=aliases,
        source_lang=SRC, target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=_join(broken), zig_impl=_join(fixed), zig_test=fixed[test_path],
        gate_mode="build", build_files=dict(fixed),
        apis_used=apis, constraints=constraints, differences=differences,
        error_signatures=sigs, side_effects=side_effects or [],
        error_behavior=error_behavior, ownership_memory=ownership, provenance=PROV)


ENTRIES = []

# ---------------------------------------------------------------- ejecutable con root_module
_EXE_OLD_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const exe = b.addExecutable(.{
        .name = "app",
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    b.installArtifact(exe);
}
'''
_EXE_NEW_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const exe = b.addExecutable(.{ .name = "app", .root_module = root });
    b.installArtifact(exe);
    const tests = b.addTest(.{ .root_module = root });
    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&exe.step);
    test_step.dependOn(&run_tests.step);
}
'''
_EXE_SRC = r'''const std = @import("std");

pub fn suma(a: i32, b: i32) i32 {
    return a + b;
}

pub fn main() !void {
    std.debug.print("suma: {d}\n", .{suma(2, 3)});
}

test "suma" {
    try std.testing.expectEqual(@as(i32, 5), suma(2, 3));
}
'''
ENTRIES.append(entry(
    "zig0.16/build-exe-root-module",
    "ejecutable 0.16 con root_module = b.createModule",
    "Compilar un ejecutable en Zig 0.16: addExecutable ya no acepta root_source_file/target/optimize; el codigo va en un std.Build.Module creado con b.createModule y el ejecutable recibe .root_module.",
    ["addExecutable root_source_file", "b.addExecutable", "createModule", "root_module", "build.zig 0.16", "ejecutable zig build", "no field named root_source_file", "migrar build.zig a 0.16"],
    {"build.zig": _EXE_OLD_BUILD, "src/main.zig": _EXE_SRC},
    {"build.zig": _EXE_NEW_BUILD, "src/main.zig": _EXE_SRC},
    "src/main.zig",
    ["error: no field named 'root_source_file' in struct 'Build.ExecutableOptions'"],
    ["std.Build.createModule", "std.Build.addExecutable", "std.Build.addTest", "std.Build.addRunArtifact", "std.Build.step", "std.Build.installArtifact"],
    ["target y optimize van en createModule, no en addExecutable",
     "el paso 'test' necesita addTest sobre el mismo root_module"],
    ["0.13/0.14: b.addExecutable(.{ .root_source_file, .target, .optimize }); 0.16: b.createModule(.{...}) y b.addExecutable(.{ .name, .root_module })"],
    side_effects=["escribe artefactos en zig-out/ con installArtifact"]))

# ---------------------------------------------------------------- libc
_LIBC_BROKEN_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .root_module = root });
    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&run_tests.step);
}
'''
_LIBC_FIXED_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
    });
    const tests = b.addTest(.{ .root_module = root });
    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&run_tests.step);
}
'''
_LIBC_SRC = r'''const std = @import("std");

extern "c" fn getpid() c_int;

test "getpid es positivo" {
    try std.testing.expect(getpid() > 0);
}
'''
ENTRIES.append(entry(
    "zig0.16/build-link-libc",
    "enlazar libc en el modulo (link_libc = true)",
    "Un modulo que llama a funciones de libc (extern \"c\", headers C) debe declarar la dependencia en el build: en 0.16 es .link_libc = true en b.createModule; sin ello el build falla antes de compilar.",
    ["dependency on libc must be explicitly specified", "link_libc", "libc", "extern c", "getpid", "enlazar libc", "zig build libc", "link_libc = true", "@cImport libc"],
    {"build.zig": _LIBC_BROKEN_BUILD, "src/main.zig": _LIBC_SRC},
    {"build.zig": _LIBC_FIXED_BUILD, "src/main.zig": _LIBC_SRC},
    "src/main.zig",
    ["error: dependency on libc must be explicitly specified in the build command"],
    ["std.Build.createModule", "std.Build.Module.link_libc", "std.Build.addTest", "std.Build.addRunArtifact"],
    ["la opcion va en el modulo (createModule), no en addTest ni en addExecutable",
     "tambien vale para modulos importados que usan libc"],
    ["0.13/0.14 habia que pasar linkLibC() al Compile; en 0.16 se declara en el modulo con .link_libc = true"],
    error_behavior="sin link_libc el build se detiene antes de compilar (exit 1)"))

# ---------------------------------------------------------------- modulo importado
_IMP_BROKEN_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .root_module = root });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run unit tests").dependOn(&run_tests.step);
}
'''
_IMP_FIXED_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const util_mod = b.createModule(.{
        .root_source_file = b.path("src/util.zig"),
        .target = target,
        .optimize = optimize,
    });
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    root.addImport("util", util_mod);
    const tests = b.addTest(.{ .root_module = root });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run unit tests").dependOn(&run_tests.step);
}
'''
_IMP_MAIN = r'''const std = @import("std");
const util = @import("util");

test "suma" {
    try std.testing.expectEqual(@as(i32, 5), util.add(2, 3));
}
'''
_IMP_UTIL = r'''pub fn add(a: i32, b: i32) i32 {
    return a + b;
}
'''
ENTRIES.append(entry(
    "zig0.16/build-add-import",
    "modulo importado por nombre (addImport)",
    "Importar un modulo por nombre (@import(\"util\")) exige registrarlo en el modulo que lo usa con addImport; un @import de ruta (\"util.zig\") no necesita nada.",
    ["no module named available within module", "addImport", "@import por nombre", "modulo importado build.zig", "no module named util", "module root", "b.createModule addImport", "dependencia entre modulos"],
    {"build.zig": _IMP_BROKEN_BUILD, "src/main.zig": _IMP_MAIN, "src/util.zig": _IMP_UTIL},
    {"build.zig": _IMP_FIXED_BUILD, "src/main.zig": _IMP_MAIN, "src/util.zig": _IMP_UTIL},
    "src/main.zig",
    ["error: no module named 'util' available within module 'root'"],
    ["std.Build.Module.addImport", "std.Build.createModule"],
    ["el nombre del modulo en addImport es el mismo que en @import",
     "un modulo solo ve los imports que se le anaden explicitamente"],
    ["sin addImport, @import(\"util\") busca un modulo con ese nombre y falla; con addImport(\"util\", util_mod) compila"]))

# ---------------------------------------------------------------- import fuera del modulo
_OUT_BROKEN_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .root_module = root });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run unit tests").dependOn(&run_tests.step);
}
'''
_OUT_FIXED_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const math_mod = b.createModule(.{
        .root_source_file = b.path("lib/math.zig"),
        .target = target,
        .optimize = optimize,
    });
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    root.addImport("math", math_mod);
    const tests = b.addTest(.{ .root_module = root });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run unit tests").dependOn(&run_tests.step);
}
'''
_OUT_BROKEN_MAIN = r'''const std = @import("std");
const math = @import("../lib/math.zig");

test "suma" {
    try std.testing.expectEqual(@as(i32, 5), math.add(2, 3));
}
'''
_OUT_FIXED_MAIN = r'''const std = @import("std");
const math = @import("math");

test "suma" {
    try std.testing.expectEqual(@as(i32, 5), math.add(2, 3));
}
'''
_OUT_MATH = r'''pub fn add(a: i32, b: i32) i32 {
    return a + b;
}
'''
ENTRIES.append(entry(
    "zig0.16/build-import-outside-module",
    "import de un archivo fuera de la carpeta del modulo",
    "Zig solo importa por ruta archivos dentro de la carpeta raiz del modulo (src/); un @import(\"../lib/x.zig\") falla. La solucion es declarar ese archivo como su propio modulo con createModule y addImport por nombre.",
    ["import of file outside module path", "@import ../ fuera del modulo", "modulo raiz src", "import fuera de src", "root_source_file carpeta", "importar archivo relativo ..", "module path"],
    {"build.zig": _OUT_BROKEN_BUILD, "src/main.zig": _OUT_BROKEN_MAIN, "lib/math.zig": _OUT_MATH},
    {"build.zig": _OUT_FIXED_BUILD, "src/main.zig": _OUT_FIXED_MAIN, "lib/math.zig": _OUT_MATH},
    "src/main.zig",
    ["error: import of file outside module path"],
    ["std.Build.createModule", "std.Build.Module.addImport", "std.Build.addTest"],
    ["el archivo importado por nombre debe ser la raiz de su modulo (root_source_file)",
     "el nombre de addImport es el que se usa en @import"],
    ["@import por ruta relativa fuera de la carpeta del modulo: error en 0.16; por modulo con nombre: correcto"]))

# ---------------------------------------------------------------- libreria dinamica (API)
_DYN_OLD_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const lib = b.addSharedLibrary(.{
        .name = "plugin",
        .root_source_file = b.path("src/plugin.zig"),
        .target = target,
        .optimize = optimize,
    });
    b.installArtifact(lib);
    b.step("test", "Run unit tests").dependOn(&lib.step);
}
'''
_DYN_FIXED_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const plugin_mod = b.createModule(.{
        .root_source_file = b.path("src/plugin.zig"),
        .target = target,
        .optimize = optimize,
    });
    const plugin = b.addLibrary(.{ .linkage = .dynamic, .name = "plugin", .root_module = plugin_mod });
    b.installArtifact(plugin);
    const tests = b.addTest(.{ .root_module = plugin_mod });
    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&plugin.step);
    test_step.dependOn(&run_tests.step);
}
'''
_PLUGIN_SRC = r'''const std = @import("std");

pub export fn plugin_add(a: i32, b: i32) i32 {
    return a + b;
}

test "plugin_add suma" {
    try std.testing.expectEqual(@as(i32, 5), plugin_add(2, 3));
}
'''
ENTRIES.append(entry(
    "zig0.16/build-shared-library",
    "libreria dinamica: addSharedLibrary -> addLibrary(.linkage = .dynamic)",
    "Compilar una libreria dinamica (.so) en Zig 0.16: b.addSharedLibrary ya no existe; se usa b.addLibrary con .linkage = .dynamic sobre un modulo creado con b.createModule.",
    ["addSharedLibrary", "libreria dinamica", "shared library", "addLibrary linkage dynamic", ".so zig build", "migrar addSharedLibrary", "export fn libreria"],
    {"build.zig": _DYN_OLD_BUILD, "src/plugin.zig": _PLUGIN_SRC},
    {"build.zig": _DYN_FIXED_BUILD, "src/plugin.zig": _PLUGIN_SRC},
    "src/plugin.zig",
    ["error: no field or member function named 'addSharedLibrary' in 'Build'"],
    ["std.Build.addLibrary", "std.Build.LibraryOptions.linkage", "std.Build.createModule", "std.Build.installArtifact"],
    ["la forma es addLibrary(.{ .linkage = .dynamic, .name, .root_module })",
     "los simbolos que se exportan a C usan pub export fn"],
    ["0.13/0.14: b.addSharedLibrary(.{ .name, .root_source_file, ... }); 0.16: b.addLibrary(.{ .linkage = .dynamic, .name, .root_module })"],
    side_effects=["instala la libreria en zig-out/lib con installArtifact"]))

# ---------------------------------------------------------------- PIC en libreria dinamica
_PIC_BROKEN_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const plugin_mod = b.createModule(.{
        .root_source_file = b.path("src/plugin.zig"),
        .target = target,
        .optimize = optimize,
        .pic = false,
    });
    const plugin = b.addLibrary(.{ .linkage = .dynamic, .name = "plugin", .root_module = plugin_mod });
    const tests = b.addTest(.{ .root_module = plugin_mod });
    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&plugin.step);
    test_step.dependOn(&run_tests.step);
}
'''
_PIC_FIXED_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const plugin_mod = b.createModule(.{
        .root_source_file = b.path("src/plugin.zig"),
        .target = target,
        .optimize = optimize,
        .pic = true,
    });
    const plugin = b.addLibrary(.{ .linkage = .dynamic, .name = "plugin", .root_module = plugin_mod });
    const tests = b.addTest(.{ .root_module = plugin_mod });
    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&plugin.step);
    test_step.dependOn(&run_tests.step);
}
'''
ENTRIES.append(entry(
    "zig0.16/build-dynamic-library-pic",
    "libreria dinamica exige PIC (.pic = true)",
    "Una libreria dinamica necesita codigo independiente de posicion: el modulo declara .pic = true (en 0.16, .pic = false con linkage dynamic no compila).",
    ["Position Independent Code", "dynamic linking requires enabling PIC", "pic = true", "fPIC zig", "libreria dinamica PIC", "unable to create module root", "linking dinamico pic"],
    {"build.zig": _PIC_BROKEN_BUILD, "src/plugin.zig": _PLUGIN_SRC},
    {"build.zig": _PIC_FIXED_BUILD, "src/plugin.zig": _PLUGIN_SRC},
    "src/plugin.zig",
    ["error: unable to create module 'root': dynamic linking requires enabling Position Independent Code"],
    ["std.Build.createModule", "std.Build.Module.pic", "std.Build.addLibrary", "std.Build.addTest"],
    ["pic es una opcion del modulo, no del Compile",
     "sin defecto explicito, la libreria dinamica decide PIC; forzar pic = false rompe el enlace dinamico"],
    ["0.16: el modulo de una libreria dinamica no puede declarar pic = false"],
    error_behavior="el build falla al crear el modulo raiz de la libreria"))

# ---------------------------------------------------------------- paso de tests
_TEST_OLD_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const tests = b.addTest(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run unit tests").dependOn(&run_tests.step);
}
'''
_TEST_FIXED_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .root_module = root });
    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&run_tests.step);
}
'''
_TEST_MAIN = r'''const std = @import("std");

test "la aritmetica basica" {
    try std.testing.expectEqual(@as(i32, 4), 2 + 2);
}
'''
ENTRIES.append(entry(
    "zig0.16/build-test-step",
    "paso zig build test (addTest + addRunArtifact + step)",
    "Un paso 'test' que ejecuta los tests del modulo en 0.16: addTest recibe .root_module, addRunArtifact lo ejecuta y el paso b.step(\"test\") depende del run. Asi zig build test corre los tests.",
    ["zig build test", "addTest", "addRunArtifact", "b.step test", "paso de tests build.zig", "run tests zig build", "addTest root_source_file", "tests en build.zig"],
    {"build.zig": _TEST_OLD_BUILD, "src/main.zig": _TEST_MAIN},
    {"build.zig": _TEST_FIXED_BUILD, "src/main.zig": _TEST_MAIN},
    "src/main.zig",
    ["error: no field named 'root_source_file' in struct 'Build.TestOptions'"],
    ["std.Build.addTest", "std.Build.addRunArtifact", "std.Build.step", "std.Build.createModule"],
    ["addTest(.{ .root_module }) exige un modulo; el run debe pasar por addRunArtifact",
     "un paso 'test' sin dependencia del run no ejecuta nada y pasa en silencio"],
    ["0.13/0.14: b.addTest(.{ .root_source_file, .target, .optimize }); 0.16: b.addTest(.{ .root_module })"]))

# ---------------------------------------------------------------- C en el build
_CSRC_BROKEN_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .root_module = root });
    tests.addCSourceFile(.{ .file = b.path("src/c/add.c"), .flags = &.{} });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run unit tests").dependOn(&run_tests.step);
}
'''
_CSRC_FIXED_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    root.addCSourceFiles(.{ .root = b.path("src/c"), .files = &.{"add.c"}, .flags = &.{} });
    const tests = b.addTest(.{ .root_module = root });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run unit tests").dependOn(&run_tests.step);
}
'''
_CSRC_MAIN = r'''const std = @import("std");

extern fn c_add(a: c_int, b: c_int) c_int;

test "suma en C" {
    try std.testing.expectEqual(@as(c_int, 5), c_add(2, 3));
}
'''
_CSRC_C = r'''int c_add(int a, int b) {
    return a + b;
}
'''
ENTRIES.append(entry(
    "zig0.16/build-c-source-files",
    "compilar C junto al modulo (addCSourceFiles)",
    "Compilar un .c en el build de Zig 0.16: addCSourceFile ya no existe en el Compile; los fuentes C se anaden al modulo con addCSourceFiles (root, files, flags) y el Zig los enlaza con extern fn.",
    ["addCSourceFile", "addCSourceFiles", "compilar C con zig build", "extern fn C", "funcion C propia", "c_add", "C en build.zig", "no field addCSourceFile Compile"],
    {"build.zig": _CSRC_BROKEN_BUILD, "src/main.zig": _CSRC_MAIN, "src/c/add.c": _CSRC_C},
    {"build.zig": _CSRC_FIXED_BUILD, "src/main.zig": _CSRC_MAIN, "src/c/add.c": _CSRC_C},
    "src/main.zig",
    ["error: no field or member function named 'addCSourceFile' in 'Build.Step.Compile'"],
    ["std.Build.Module.addCSourceFiles", "std.Build.Module.AddCSourceFilesOptions", "std.Build.addTest", "std.Build.addRunArtifact"],
    ["los ficheros C se anaden al modulo, no al Compile",
     "root es la carpeta de los ficheros y files son rutas relativas a ella"],
    ["0.13/0.14: compile.addCSourceFile(.{ .file, .flags }); 0.16: module.addCSourceFiles(.{ .root, .files, .flags })"]))

CONTRACTS = {e["operation_id"]: _c(None, None, None, [], **_SKIP) for e in ENTRIES}
