"""Recetas de DIAGNOSTICO para firmas minadas sin receta (`zig0.16/diag-mined-*`).

Origen: `var/mined/signatures.jsonl` + `eval/mined_labels.tsv` (ola 5). Cada
receta reune firmas afines y lleva un ejemplo ROTO (`py_ref`) y su arreglo
verificado (`zig_impl`/`zig_test`) con `zig test` 0.16.0. Las firmas de
`error_signatures` son la forma normalizada de la mineria (`uN`, `N`, comodines
`_` entre comillas) con valores concretos donde el emparejador de
`pyzig.check.match_signature` necesita un hueco-litero para distinguir recetas.

Las firmas totalmente genericas (`root source file struct '_' has no member
named '_'`, `use of undeclared identifier '_'`, `expected type '_', found '_'`,
`no field or member function named '_' in '_'`) NO se ponen en
`error_signatures`: comparten plantilla con recetas mas antiguas y el
emparejador se abstiene (huecos solo comodin). Para esas, la receta ensena el
METODO (buscar el nombre nuevo en la std instalada) y NO se reetiqueta la firma
minada; asi se evita una autoconsistencia falsa.
"""
from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"; PY = "3.12"
PROV = "firmas de var/mined/signatures.jsonl; ejemplo roto y arreglo verificados con zig 0.16.0 (zig test / zig build test)"
SRC = "zig-0.16"
HDR = 'const std = @import("std");\n\n'
_SKIP = dict(type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
             skip_reason="diagnostico de error del compilador: sin driver diferencial")

#Metodo para las firmas "no member named" / "no field or member function named":
#  STD_DIR="$(zig env | sed -n 's/.*"std_dir" = "\(.*\)".*/\1/p')"
#  ziggrep -Fn "pub fn <nombre>" "$STD_DIR"     # o: zig std | ziggrep -Fn <nombre>
#Los renombrados mas vistos en signatures.jsonl (apis del contexto de las firmas):
#  std.fs.cwd -> std.Io.Dir (abrir con std.Io.Dir.cwd / openDir)
#  std.fs.openDirAbsolute -> std.Io.Dir.openDir / std.fs.cwd().openDir (0.16: std.Io.Dir)
#  std.fs.openFileAbsolute -> std.Io.Dir.openFile / readFileAlloc
#  std.io.getStdOut -> std.Io.File.stdout()
#  std.Thread.sleep / std.time.sleep -> std.Io.sleep
#  std.Thread.Mutex -> std.Io.Mutex
#  std.process.Child.run -> std.process.run
#  std.fmt.fmtSliceHexLower -> std.fmt.bytesToHex
#  std.mem.span (sigue existiendo: pasar .ptr de un [:0]const u8)
#  std.time.nanoTimestamp -> std.Io.Timestamp.now / std.time.Instant.now
#  std.testing.expectCrash -> sin equivalente directo: comprobar term.signal del hijo
METHOD = (
    "firma dependiente del caso: para 'no member named'/'no field or member function named' "
    "no hay un unico arreglo; busca el nombre nuevo con `zig std` o en la fuente de std "
    "que senala `zig env` (STD_DIR=$(zig env | sed -n 's/.*\"std_dir\" = \"\\(.*\\)\".*/\\1/p'); "
    "ziggrep -Fn 'pub fn <nombre>' \"$STD_DIR\"). Renombrados vistos en las firmas minadas: "
    "std.fs.cwd/std.fs.openDirAbsolute/std.fs.openFileAbsolute -> std.Io.Dir; "
    "std.io.getStdOut -> std.Io.File.stdout(); std.Thread.sleep/std.time.sleep -> std.Io.sleep; "
    "std.Thread.Mutex -> std.Io.Mutex; std.process.Child.run -> std.process.run; "
    "std.fmt.fmtSliceHexLower -> std.fmt.bytesToHex; std.time.nanoTimestamp -> std.Io.Timestamp.now."
)


def entry(oid, name, intent, aliases, broken, fixed, tests, apis, constraints,
          differences, sigs, *, build_files=None, error_behavior="error de compilacion",
          ownership="sin asignaciones"):
    d = dict(
        operation_id=oid, name=name, intent=intent, aliases=aliases,
        source_lang=SRC, target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=broken, zig_impl=fixed,
        zig_test=(HDR + fixed + "\n\n" + tests) if tests else None,
        apis_used=apis, constraints=constraints, differences=differences,
        error_signatures=sigs, side_effects=[], error_behavior=error_behavior,
        ownership_memory=ownership, provenance=PROV,
    )
    if build_files is not None:
        d["gate_mode"] = "build"
        d["build_files"] = build_files
    return d


ENTRIES = []

# ---------------------------------------------------------------- member format
ENTRIES.append(entry(
    "zig0.16/diag-mined-member-format",
    "error 'no field or member function named format': usar std.fmt.bufPrint",
    "Un []const u8 no expone el metodo .format(): en Zig 0.16 se formatea con std.fmt.bufPrint (buffer propio) o std.fmt.allocPrint (asigna).",
    ["no field or member function named format", "no member named format", "format en slice", "metodo format en zig", "formatear slice", "buffer de formato", "bufPrint", "metodo format no existe", "nombre renombrado en std 0.16"],
    r'''const std = @import("std");

test "format sobre slice" {
    const s: []const u8 = "abc";
    const out = s.format(.{});
    try std.testing.expectEqualStrings("abc", out);
}''',
    r'''pub fn formatea(buf: []u8, s: []const u8) ![]const u8 {
    return std.fmt.bufPrint(buf, "<{s}>", .{s});
}''',
    r'''test "bufPrint reemplaza a str.format" {
    var buf: [32]u8 = undefined;
    try std.testing.expectEqualStrings("<abc>", try formatea(&buf, "abc"));
}''',
    ["std.fmt.bufPrint", "std.fmt.allocPrint"],
    ["bufPrint no asigna: NoSpaceLeft si el buffer es corto", "para texto dinamico usar allocPrint con el allocator del llamante", METHOD],
    ["0.16: std.fmt.bufPrint/allocPrint reemplazan al metodo .format() de las slices",
     "si el nombre del error no es 'format', usa el metodo de busqueda de constraints"],
    ["error: no field or member function named 'format' in '[]const u8'"]))

# ---------------------------------------------------------------- undeclared identifier
ENTRIES.append(entry(
    "zig0.16/diag-mined-undeclared-ident",
    "use of undeclared identifier: falta calificar o importar el nombre",
    "Un identificador que el compilador no conoce suele ser una llamada sin calificar (expectEqual en lugar de std.testing.expectEqual), un @import ausente o un nombre de otra version de std.",
    ["use of undeclared identifier", "identificador no declarado", "falta std.testing", "expectEqual no declarado", "import ausente", "nombre no conocido", "sin calificar", "namespace incorrecto", "nombre renombrado en std 0.16"],
    r'''const std = @import("std");

test "expectEqual sin calificar" {
    try expectEqual(@as(u32, 2), 1 + 1);
}''',
    r'''pub fn sumaUnUno(x: u32) u32 {
    return x + 1;
}''',
    r'''test "expectEqual calificado" {
    try std.testing.expectEqual(@as(u32, 2), sumaUnUno(1));
    try std.testing.expect(sumaUnUno(1) > 0);
}''',
    ["std.testing.expectEqual", "std.testing.expect", "@import"],
    ["si el nombre es de la std, calificalo con std.<area>.<nombre>; si es una constante propia, declarala antes de usarla", METHOD],
    ["firma minada 'use of undeclared identifier '_'' es generica (comparte plantilla con 'builtin'): el matcher se abstiene; mira el nombre concreto del error",
     "si el nombre concreto cambio de sitio en std, usa el metodo de busqueda de constraints"],
    ["error: use of undeclared identifier 'expectEqual'"]))

# ---------------------------------------------------------------- asm constraint
ENTRIES.append(entry(
    "zig0.16/diag-mined-asm-constraint",
    "invalid constraint: '_' en inline asm (restriccion de registro invalida)",
    "El mensaje 'invalid constraint' NO es de tipos ni de comptime: viene de una restriccion de asm inline. '=X' no existe en el backend x86 de 0.16; las salidas usan '=r' (registro general), '=x' (SSE) o '=m' (memoria), y las entradas 'r'/'x'/'m'.",
    ["invalid constraint", "restriccion asm invalida", "inline asm constraint", "asm =X", "registro asm", "constraint asm", "restriccion de registro", "asm invalido"],
    r'''const std = @import("std");

fn sumaUno(x: u32) u32 {
    return asm (
        \\ mov %[in], %[out]
        \\ add $1, %[out]
        : [out] "=X" (-> u32),
        : [in] "r" (x),
    );
}

test "asm con restriccion invalida" {
    try std.testing.expectEqual(@as(u32, 2), sumaUno(1));
}''',
    r'''pub fn sumaUno(x: u32) u32 {
    return asm (
        \\ mov %[in], %[out]
        \\ add $1, %[out]
        : [out] "=r" (-> u32),
        : [in] "r" (x),
    );
}''',
    r'''test "restriccion =r compila y suma" {
    try std.testing.expectEqual(@as(u32, 8), sumaUno(7));
}''',
    ["asm inline", "constraint =r"],
    ["asm inline es especifico de arquitectura: la receta se verifica en x86_64-linux", "no silenciar restricciones con restricciones de memoria sin saber el coste"],
    ["0.16: '=X' produce 'invalid constraint: '=X''; '=r' es la restriccion de salida en registro general"],
    ["error: invalid constraint: '=X'"]))

# ---------------------------------------------------------------- unused / discard
ENTRIES.append(entry(
    "zig0.16/diag-mined-unused-discard",
    "unused local constant / pointless discard: usar o descartar con intencion",
    "Zig exige que cada local se use. Una const sin usar es error; un '_ = x' despues de haber usado x es 'pointless discard'. La salida es quitar la variable, usarla de verdad o (si se ignora a proposito) descartar el resultado de la llamada que la produjo.",
    ["unused local constant", "pointless discard of local variable", "pointless discard of local constant", "const sin usar", "descarto una variable ya usada", "variable no utilizada", "zig se queja de variable sin usar", "discard innecesario"],
    r'''const std = @import("std");

fn valor() u32 { return 7; }

test "const sin usar" {
    const sin_usar: u32 = 1;
    _ = valor();
}

test "descarto tras usar" {
    var x: u32 = 1;
    x += 1;
    _ = x;
}''',
    r'''pub fn doble(x: u32) u32 {
    return x * 2;
}

pub fn descartarResultado() void {
    _ = std.fmt.bufPrint(&[_]u8{}, "", .{}) catch {};
}''',
    r'''test "constante usada y resultado descartado una sola vez" {
    try std.testing.expectEqual(@as(u32, 14), doble(7));
    descartarResultado();
}''',
    ["std.testing.expectEqual"],
    ["si la variable sobra, borrala; si se ignora un valor a proposito, descartalo en el punto de produccion (_ = f() catch {}), no despues de haberlo usado"],
    ["0.16: 'unused local constant' y 'pointless discard of local variable' son errores, no advertencias"],
    ["error: unused local constant",
     "error: pointless discard of local variable",
     "error: pointless discard of local constant"]))

# ---------------------------------------------------------------- nombres duplicados
ENTRIES.append(entry(
    "zig0.16/diag-mined-duplicate-names",
    "error de compilador: identificadores repetidos en un ambito",
    "Dos const locales o dos campos de struct comparten identificador y el compilador lo rechaza. Renombrar una de las declaraciones resuelve 'redeclaration of local constant' y el error de miembro repetido.",
    ["identificadores repetidos", "const repetida", "renombrar declaracion", "redeclaration of local constant", "struct member repetido", "nombre local repetido",
     "diagnostico de compilacion: ambito lexico, declaracion local y campo de struct", "error de compilador Zig 0.16 por identificador en uso",
     "redeclaracion de constante local en el mismo bloque", "miembro de struct con nombre ya declarado",
     "tabla de simbolos y ambito lexico: redeclaracion de identificador local",
     "mensaje del compilador Zig: redeclaracion de constante local, campo de struct repetido",
     "diagnostico estatico de codigo Zig 0.16, no comportamiento en tiempo de ejecucion"],
    r'''const std = @import("std");

const Punto = struct { x: u8, x: u8 };

test "nombres repetidos" {
    const x: u32 = 1;
    const x: u32 = 2;
    const p = Punto{ .x = 1, .x = 2 };
    try std.testing.expectEqual(@as(u32, 2), x + p.x);
}''',
    r'''const Punto = struct { x: u8, y: u8 };

pub fn sumaPunto(p: Punto) u16 {
    const primero: u16 = p.x;
    const segundo: u16 = p.y;
    return primero + segundo;
}''',
    r'''test "nombres distintos" {
    try std.testing.expectEqual(@as(u16, 3), sumaPunto(.{ .x = 1, .y = 2 }));
}''',
    ["std.testing.expectEqual"],
    ["el error es de nombres: mantener los tipos y renombrar solo una declaracion"],
    ["0.16: tanto la redeclaracion local como el campo repetido son errores de compilacion"],
    ["error: redeclaration of local constant 'x'",
     "error: duplicate struct member name 'x'",
     "error: duplicate struct member name 'std'"]))

# ---------------------------------------------------------------- rango de enteros
ENTRIES.append(entry(
    "zig0.16/diag-mined-int-range",
    "type 'uN' cannot represent integer value: elegir ancho o convertir",
    "Un literal no cabe en el tipo destino (300 en u8, -1 en usize). O se ensancha el tipo (u16, i32) o se transforma el valor: @truncate conserva los bits bajos, @intCast verifica rango en Debug/ReleaseSafe, std.math.cast devuelve null si no cabe.",
    ["cannot represent integer value", "literal no cabe en u8", "usize negativo", "valor fuera de rango", "integer overflow literal", "tipo entero demasiado pequeno", "@intCast de literal", "truncate literal"],
    r'''const std = @import("std");

test "literal fuera de rango" {
    const pequeno: u8 = 300;
    const signo: usize = -1;
    try std.testing.expect(pequeno > 0 and signo > 0);
}''',
    r'''pub fn bajoBits(x: u16) u8 {
    return @truncate(x);
}

pub fn ancho(x: i32) usize {
    return std.math.cast(usize, x) orelse 0;
}''',
    r'''test "conversion explicita" {
    try std.testing.expectEqual(@as(u8, 44), bajoBits(300));
    try std.testing.expectEqual(@as(usize, 7), ancho(7));
    try std.testing.expectEqual(@as(usize, 0), ancho(-1));
}''',
    ["@truncate", "std.math.cast"],
    ["@truncate(300) = 44 (descarta bits altos sin avisar); @intCast(-1 a usize) panica en Debug/ReleaseSafe; std.math.cast devuelve null"],
    ["0.16: asignar un literal que no cabe al tipo es error de compilacion, no un wrap silencioso"],
    ["error: type 'u8' cannot represent integer value '300'",
     "error: type 'usize' cannot represent integer value '-1'"]))

# ---------------------------------------------------------------- comptime_int de runtime
ENTRIES.append(entry(
    "zig0.16/diag-mined-comptime-flow",
    "comptime_int/comptime_float depende de control flow de runtime: dar tipo concreto",
    "Si una rama de un if depende de una variable de runtime, el valor inferido no puede quedarse como comptime_int/comptime_float: el compilador exige un tipo concreto. Anadir la anotacion (: u32, : f64) o una conversion @as rompe la dependencia.",
    ["comptime-only type depends on runtime control flow", "comptime_int depends on runtime", "comptime_float depends on runtime", "tipo comptime en runtime", "valor comptime depende de if", "anotar tipo en if", "inferencia comptime en rama"],
    r'''const std = @import("std");

fn eligeEntero(c: bool) u32 {
    const n = if (c) @as(comptime_int, 1) else 2;
    return n;
}

fn eligeFloat(c: bool) f64 {
    const n: comptime_float = if (c) 1.5 else 2.5;
    return n;
}

test "comptime en runtime" {
    try std.testing.expectEqual(@as(u32, 1), eligeEntero(true));
    try std.testing.expectEqual(@as(f64, 1.5), eligeFloat(true));
}''',
    r'''pub fn eligeEntero(c: bool) u32 {
    const n: u32 = if (c) 1 else 2;
    return n;
}

pub fn eligeFloat(c: bool) f64 {
    const n: f64 = if (c) 1.5 else 2.5;
    return n;
}''',
    r'''test "tipo concreto en ambas ramas" {
    try std.testing.expectEqual(@as(u32, 1), eligeEntero(true));
    try std.testing.expectEqual(@as(u32, 2), eligeEntero(false));
    try std.testing.expectEqual(@as(f64, 1.5), eligeFloat(true));
}''',
    ["@as", "anotacion de tipo"],
    ["la anotacion va en la constante (o en cada rama), no en el return: asi el if ya no produce un tipo comptime-only"],
    ["0.16: comptime_int/comptime_float solo existen mientras el valor es conocido en compilacion; el control flow de runtime los invalida"],
    ["error: value with comptime-only type 'comptime_int' depends on runtime control flow",
     "error: value with comptime-only type 'comptime_float' depends on runtime control flow"]))

# ---------------------------------------------------------------- indice de vector
ENTRIES.append(entry(
    "zig0.16/diag-mined-vector-index",
    "error 'vector index not comptime known': @Vector requiere indice comptime",
    "Indexar un @Vector con un valor de runtime es error: el indice debe ser conocido en compilacion. Para un indice de runtime, convertir el @Vector a [N]T (`const a: [N]T = v;`) e indexar el array.",
    ["vector index not comptime known", "indice de vector runtime", "indexar @Vector", "@Vector a array", "SIMD index comptime"],
    r'''const std = @import("std");

fn at(v: @Vector(4, u32), i: usize) u32 {
    return v[i];
}

test "indice de vector" {
    const v: @Vector(4, u32) = .{ 1, 2, 3, 4 };
    try std.testing.expectEqual(@as(u32, 3), at(v, 2));
}''',
    r'''pub fn at(v: @Vector(4, u32), i: usize) u32 {
    const a: [4]u32 = v;
    return a[i];
}''',
    r'''test "array si admite indice de runtime" {
    const v: @Vector(4, u32) = .{ 1, 2, 3, 4 };
    try std.testing.expectEqual(@as(u32, 3), at(v, 2));
}''',
    ["@Vector", "coercion vector a array"],
    ["la conversion a array es una copia; si el vector es grande, replantear el acceso (constantes de indexacion) antes de copiar"],
    ["0.16: indexar @Vector con un valor de runtime es error de compilacion"],
    ["error: vector index not comptime known"]))

# ---------------------------------------------------------------- bitCast
ENTRIES.append(entry(
    "zig0.16/diag-mined-bitcast-size",
    "@bitCast size mismatch: mismo tamano o conversion entera, no reinterpretacion",
    "@bitCast NO cambia el numero de bits: origen y destino deben tener el mismo ancho. Para ensanchar, extender primero el valor (@as(i64, x) o @as(u32, x)) y luego hacer bitCast si se quiere reinterpretar; para estrechar, @truncate.",
    ["bitCast size mismatch", "@bitCast tamano", "bitcast u64 i32", "reinterpretar bits de distinto ancho", "bitcast mismatch", "bitCast extension", "bitcast ancho"],
    r'''const std = @import("std");

fn firmados(x: i32) u64 { return @bitCast(x); }
fn cortos(x: u16) u32 { return @bitCast(x); }

test "bitCast incompatible" {
    try std.testing.expectEqual(@as(u64, 0), firmados(0));
    try std.testing.expectEqual(@as(u32, 0), cortos(0));
}''',
    r'''pub fn firmados(x: i32) u64 {
    return @bitCast(@as(i64, x));
}

pub fn cortos(x: u16) u32 {
    return @as(u32, x);
}''',
    r'''test "extension antes de reinterpretar" {
    try std.testing.expectEqual(@as(u64, 0xFFFF_FFFF_FFFF_FFFF), firmados(-1));
    try std.testing.expectEqual(@as(u32, 65535), cortos(65535));
}''',
    ["@bitCast", "@as", "@truncate"],
    ["@bitCast entre i32 y u32 (mismo ancho) es valido; entre i32 y u64 no. Para extension con signo usar @as(i64, x); para ensanchar sin signo, @as(u32, x)"],
    ["0.16: @bitCast exige exactamente el mismo numero de bits en origen y destino"],
    ["error: @bitCast size mismatch: destination type 'u64' has 64 bits but source type 'i32' has 32 bits",
     "error: @bitCast size mismatch: destination type 'u32' has 32 bits but source type 'u16' has 16 bits"]))

# ---------------------------------------------------------------- error union ignorada
ENTRIES.append(entry(
    "zig0.16/diag-mined-error-union",
    "error union is ignored: propagar, capturar o comprobar el error",
    "Llamar una funcion !T y abandonar el resultado sin try/catch/if es error en Zig (a diferencia de Python, donde una excepcion no capturada solo falla en runtime). Usar try para propagar, catch para dar valor por defecto o std.testing.expectError en tests.",
    ["error union is ignored", "ignorar error", "try obligatorio", "llamada sin try", "resultado de error ignorado", "error no manejado zig", "catch expectError"],
    r'''const std = @import("std");

fn riesgo(x: u8) !u8 {
    if (x == 0) return error.Cero;
    return x;
}

test "errores ignorados" {
    riesgo(2);
    riesgo(0);
}''',
    r'''pub fn riesgo(x: u8) !u8 {
    if (x == 0) return error.Cero;
    return x;
}

pub fn seguro(x: u8) u8 {
    return riesgo(x) catch 0;
}''',
    r'''test "try y expectError" {
    try std.testing.expectEqual(@as(u8, 2), try riesgo(2));
    try std.testing.expectError(error.Cero, riesgo(0));
    try std.testing.expectEqual(@as(u8, 0), seguro(0));
}''',
    ["try", "catch", "std.testing.expectError"],
    ["catch {} descarta el error: solo es correcto si la perdida es intencionada; en tests usar expectError"],
    ["0.16: ignorar una error union es error de compilacion con nota 'consider using try, catch, or if'"],
    ["error: error union is ignored"]))

# ---------------------------------------------------------------- coercion de punteros
ENTRIES.append(entry(
    "zig0.16/diag-mined-pointer-coercion",
    "coerciones de puntero/array/slice: &array, indexacion y tipos const",
    "Un *const u8 no es un slice: para pasar un array como slice usar `arr[0..]` (o `&arr` cuando el tipo destino es *[N]T). Un [*]T (many) no se convierte en *T (single): indexar el many (`mp[0]`) o pasar *T. Los punteros const requieren tipos *const en la firma.",
    ["expected type found const pointer", "many pointer to single pointer", "single pointer from many", "array a slice", "puntero a array como slice", "coercion de punteros", "pointer slice coercion", "ptr const a slice", "no puedo pasar array a slice",
     "diagnostico de compilacion Zig 0.16: coerciones implicitas entre puntero, array y slice",
     "error de tipos en tiempo de compilacion: many pointer, single pointer, const qualifier"],
    r'''const std = @import("std");

fn comoSlice(p: *const u8) []const u8 { return p; }
fn uno(mp: [*]u8) u8 { const p: *u8 = mp; return p.*; }

test "coerciones invalidas" {
    const a = [_]u8{ 1, 2, 3 };
    try std.testing.expectEqual(@as(usize, 3), comoSlice(&a[0]).len);
    try std.testing.expectEqual(@as(u8, 1), uno(&a));
}''',
    r'''pub fn comoSlice(a: *const [3]u8) []const u8 {
    return a[0..];
}

pub fn uno(mp: [*]const u8) u8 {
    return mp[0];
}''',
    r'''test "slice desde array y many indexado" {
    const a = [_]u8{ 1, 2, 3 };
    try std.testing.expectEqual(@as(usize, 3), comoSlice(&a).len);
    try std.testing.expectEqual(@as(u8, 1), uno(&a));
}''',
    ["slices", "many pointer", "const pointer"],
    ["un slice guarda longitud; un puntero no: hay que decir explicitamente `a[0..]` para construir el slice",
     "de [*]const u8 a *const u8 se puede indexar (`mp[0]`) pero el resultado es un valor, no un puntero prestado"],
    ["0.16: las coercion implicitas entre *const T, [N]T, []T y [*]T son limitadas; el compilador no adivina la longitud"],
    ["error: expected type '[]const u8', found '*const u8'",
     "error: expected type '[]const u8', found '*[4]u8'",
     "error: cannot implicitly convert many pointer to single pointer"]))

# ---------------------------------------------------------------- @embedFile fuera del paquete
_EMBED_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const root = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .root_module = root });
    b.step("test", "Run unit tests").dependOn(&b.addRunArtifact(tests).step);
}
'''
_EMBED_MAIN = r'''const std = @import("std");
const datos = @embedFile("datos.txt");
test "embed dentro del paquete" {
    try std.testing.expectEqualStrings("hola-embebido\n", datos);
}
'''
ENTRIES.append(entry(
    "zig0.16/diag-mined-embed-outside",
    "error 'embed of file outside package path': @embedFile dentro del root",
    "@embedFile solo puede leer recursos dentro del root del paquete/modulo. Una ruta '../../etc/...' se rechaza aunque el recurso exista: copiar el recurso a src/ y usar una ruta relativa a ese root.",
    ["embed of file outside package path", "embedFile fuera del paquete", "@embedFile relativo", "recurso embebido", "ruta de embed fuera del root", "embed path",
     "diagnostico de compilacion @embedFile: ruta resuelta dentro del root del modulo",
     "error de compilador Zig 0.16: recurso embebido fuera del paquete",
     "no es operacion de E/S en tiempo de ejecucion"],
    r'''const std = @import("std");
const datos = @embedFile("../../etc/hostname");
test "embed fuera del paquete" { try std.testing.expect(datos.len > 0); }''',
    _EMBED_MAIN,
    None,
    ["@embedFile", "std.Build.createModule"],
    ["el archivo embebido se copia al binario en compilacion: no cambia en runtime", "el gate usa gate_mode=build para que el fixture viva junto a src/main.zig"],
    ["0.16: @embedFile exige que la ruta resuelva dentro del root del modulo; pasar por dirs superiores es error",
     "la ruta es relativa al fichero que llama, no al directorio de trabajo del build"],
    ["error: embed of file outside package path: '../../etc/hostname'"],
    build_files={"build.zig": _EMBED_BUILD, "src/main.zig": _EMBED_MAIN,
                 "src/datos.txt": "hola-embebido\n"},
    ownership="recurso embebido en el binario; sin asignacion"))

# ---------------------------------------------------------------- mismo archivo en dos modules
_MOD_BUILD = r'''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const comun = b.createModule(.{
        .root_source_file = b.path("src/comun.zig"),
        .target = target,
        .optimize = optimize,
    });
    const mod_a = b.createModule(.{
        .root_source_file = b.path("src/a.zig"),
        .target = target,
        .optimize = optimize,
    });
    const mod_b = b.createModule(.{
        .root_source_file = b.path("src/b.zig"),
        .target = target,
        .optimize = optimize,
    });
    mod_a.addImport("comun", comun);
    mod_b.addImport("comun", comun);
    const ta = b.addTest(.{ .root_module = mod_a });
    const tb = b.addTest(.{ .root_module = mod_b });
    const step = b.step("test", "Run unit tests");
    step.dependOn(&b.addRunArtifact(ta).step);
    step.dependOn(&b.addRunArtifact(tb).step);
}
'''
_MOD_COMUN = r'''pub const valor: u32 = 7;
'''
_MOD_A = r'''const std = @import("std");
const comun = @import("comun");
test "modulo A comparte el modulo comun" {
    try std.testing.expectEqual(@as(u32, 7), comun.valor);
}
'''
_MOD_B = r'''const std = @import("std");
const comun = @import("comun");
test "modulo B usa el MISMO modulo comun" {
    try std.testing.expectEqual(@as(u32, 7), comun.valor);
}
'''
ENTRIES.append(entry(
    "zig0.16/diag-mined-module-conflict",
    "error 'file exists in modules': compartir un modulo creado con createModule",
    "Cuando el MISMO root_source_file se registra en dos build modules con configuraciones distintas, Zig 0.16 avisa de que ese root existe en modA y modB. La solucion es crear UN modulo comun con b.createModule y pasarlo a ambos con addImport.",
    ["file exists in modules", "mismo root en dos modulos", "modulo duplicado", "addImport comun", "conflicto de modulos", "two modules same root"],
    r'''const std = @import("std");
// build.zig roto: dos createModule con el MISMO root_source_file (src/comun.zig)
// y cada modulo importa el fichero directamente en lugar de compartir el modulo.
const comun_a = b.createModule(.{ .root_source_file = b.path("src/comun.zig"), .target = target, .optimize = optimize });
const comun_b = b.createModule(.{ .root_source_file = b.path("src/comun.zig"), .target = target, .optimize = optimize });
mod_a.addImport("comun", comun_a);
mod_b.addImport("comun", comun_b);''',
    _MOD_BUILD,
    None,
    ["std.Build.createModule", "std.Build.Module.addImport"],
    ["un modulo compartido tiene una sola configuracion (target/optimize/pic) para todos los importadores", "el gate usa gate_mode=build con dos modulos que comparten el mismo objeto modulo"],
    ["0.16: los modulos son unidades de compilacion; el mismo root en dos modulos puede resolverse a artefactos distintos",
     "la firma minada es generica en los nombres de modulo: aqui se concreta como modA/modB"],
    ["error: file exists in modules 'modA' and 'modB'"],
    build_files={"build.zig": _MOD_BUILD, "src/comun.zig": _MOD_COMUN,
                 "src/a.zig": _MOD_A, "src/b.zig": _MOD_B},
    ownership="modulos creados en el build; sin memoria del usuario"))

CONTRACTS = {e["operation_id"]: _c(None, None, None, [], **_SKIP) for e in ENTRIES}
