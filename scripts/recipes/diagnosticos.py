"""Recetas de DIAGNOSTICO de errores de compilacion de Zig 0.16.0 (operation_id `zig0.16/diag-*`).

`py_ref` guarda el codigo Zig ROTO (el que produce el error); `zig_impl`/`zig_test`
guardan el arreglo verificado con `zig test`. `error_signatures` son lineas `error:`
REALES copiadas de compilar el codigo roto con zig 0.16.0 (sin ruta ni posicion,
sin el nombre de archivo). Las firmas de mineria con comodines (`_`/`N`) se
sustituyen por el nombre real que imprime el compilador. Si una firma no se
reproduce, no hay receta para ella."""
from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"; PY = "3.12"; PROV = "errores copiados de `zig test` 0.16.0 (~/.local/bin/zig); arreglo verificado con `zig test`"
SRC = "zig-0.16"
HDR = 'const std = @import("std");\n\n'
_SKIP = dict(type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
             skip_reason="diagnostico de error del compilador: sin driver diferencial")


def entry(oid, name, intent, aliases, broken, fixed, tests, apis, constraints, differences,
          sigs, side_effects=None, error_behavior="", ownership=""):
    return dict(
        operation_id=oid, name=name, intent=intent, aliases=aliases,
        source_lang=SRC, target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
        py_ref=broken, zig_impl=fixed, zig_test=HDR + fixed + "\n\n" + tests,
        apis_used=apis, constraints=constraints, differences=differences,
        error_signatures=sigs, side_effects=side_effects or [],
        error_behavior=error_behavior, ownership_memory=ownership, provenance=PROV)


ENTRIES = []

# ---------------------------------------------------------------- quota de comptime
ENTRIES.append(entry(
    "zig0.16/diag-eval-branch-quota",
    "error evaluation exceeded backwards branches en comptime",
    "Un bucle o recursion en comptime supera el limite de saltos hacia atras (1000 por defecto): el compilador aborta con 'evaluation exceeded N backwards branches'. Se sube el limite con @setEvalBranchQuota dentro del bloque comptime, o se evita comptime para ese calculo.",
    ["evaluation exceeded backwards branches", "evaluation exceeded 1000 backwards branches", "setEvalBranchQuota", "@setEvalBranchQuota", "limite de saltos comptime", "bucle comptime demasiado largo", "branch quota", "bucle en comptime", "comptime loop limit", "evaluacion excedida", "1000 backwards branches", "bucle demasiado largo", "bucle comptime demasiado largo", "que hago con bucle comptime", "limite de iteraciones comptime"],
    '''const std = @import("std");

pub const SUMA_2000: u64 = blk: {
    var i: u32 = 0;
    var s: u64 = 0;
    while (i < 2000) : (i += 1) s += i;
    break :blk s;
};

test "suma comptime" {
    try std.testing.expectEqual(@as(u64, 1999000), SUMA_2000);
}''',
    '''pub const SUMA_2000: u64 = blk: {
    @setEvalBranchQuota(10_000);
    var i: u32 = 0;
    var s: u64 = 0;
    while (i < 2000) : (i += 1) s += i;
    break :blk s;
};''',
    '''test "la suma en comptime es correcta" {
    try std.testing.expectEqual(@as(u64, 1999000), SUMA_2000);
}''',
    ["@setEvalBranchQuota", "std.testing.expectEqual"],
    ["el limite cubre saltos, no iteraciones: cada iteracion de while cuenta; subirlo solo cuando el calculo es finito y conocido",
     "si el calculo es grande o crece con la entrada, mejor hacerlo en runtime (o construir la tabla con un generador) que subir el limite sin fin"],
    ["0.16 y anteriores: el limite por defecto es 1000 saltos hacia atras por bloque comptime; el compilador sugiere @setEvalBranchQuota",
     "sin @setEvalBranchQuota el mismo calculo en runtime no tiene limite"],
    ["error: evaluation exceeded 1000 backwards branches"],
    side_effects=[],
    error_behavior="error de compilacion: el limite se aplica a la evaluacion comptime, no al programa en runtime"))

# ---------------------------------------------------------------- var nunca mutada
ENTRIES.append(entry(
    "zig0.16/diag-never-mutated",
    "local variable is never mutated: var a const",
    "Zig exige que una variable local declarada con var se reasigne alguna vez; si nunca cambia, el compilador falla con 'local variable is never mutated' y sugiere const.",
    ["local variable is never mutated", "never mutated", "variable nunca mutada", "var a const", "consider using const", "variable local nunca cambia", "var sin reasignar", "unused mutable", "const en lugar de var", "variable local nunca mutada", "cambiar var por const", "nunca reasigno", "reasignar", "zig pide const"],
    '''const std = @import("std");

fn doble(x: u32) u32 {
    var resultado: u32 = x * 2;
    return resultado;
}

test "doble" {
    try std.testing.expectEqual(@as(u32, 4), doble(2));
}''',
    '''fn doble(x: u32) u32 {
    const resultado: u32 = x * 2;
    return resultado;
}''',
    '''test "doble devuelve el valor" {
    try std.testing.expectEqual(@as(u32, 4), doble(2));
}''',
    ["std.testing.expectEqual"],
    ["usa var solo si la variable se reasigna despues de la declaracion; si no, const"],
    ["0.16: la variable no mutada es error de compilacion (no advertencia)"],
    ["error: local variable is never mutated"],
    error_behavior="error de compilacion"))

# ---------------------------------------------------------------- sombreado de declaraciones
ENTRIES.append(entry(
    "zig0.16/diag-shadow-local",
    "sombreado de declaraciones: local constant, local variable, capture o parametro",
    "Zig no permite que un nombre local (const, var, captura de for/while o parametro de funcion) tenga el mismo nombre que una declaracion visible del ambito exterior. El compilador falla con 'shadows declaration of' y la linea 'declared here'. Solucion: renombrar la local o el parametro.",
    ["shadows declaration of", "local constant shadows declaration", "local variable shadows declaration", "capture shadows declaration", "function parameter shadows declaration", "sombrea declaracion", "shadowing", "variable sombra", "nombre repetido", "local shadows global", "parametro sombrea", "captura sombrea", "declared here", "_ shadows declaration"],
    '''const std = @import("std");

const limite: u32 = 10;
const x: u8 = 1;
const n: u32 = 3;
const cuenta: u32 = 1;

fn doble(n: u32) u32 {
    return n * 2;
}

test "sombra local const" {
    const limite: u32 = 20;
    try std.testing.expectEqual(@as(u32, 20), limite);
}

test "sombra de captura" {
    const arr = [_]u8{ 1, 2 };
    for (arr) |x| _ = x;
}

test "sombra local var" {
    var cuenta: u32 = 2;
    cuenta += 1;
    try std.testing.expectEqual(@as(u32, 3), cuenta);
}

test "sombra de parametro" {
    try std.testing.expectEqual(@as(u32, 4), doble(2));
}''',
    '''const limite: u32 = 10;
const x: u8 = 1;
const n: u32 = 3;
const cuenta: u32 = 1;

fn doble(m: u32) u32 {
    return m * 2;
}

fn sombrasCorregidas() u32 {
    const limiteLocal: u32 = 20;
    const arr = [_]u8{ 1, 2 };
    for (arr) |elem| _ = elem;
    var cuentaLocal: u32 = 2;
    cuentaLocal += 1;
    return limiteLocal + cuentaLocal + doble(2);
}''',
    '''test "sombras corregidas" {
    try std.testing.expectEqual(@as(u32, 27), sombrasCorregidas());
}''',
    ["std.testing.expectEqual"],
    ["el error es de nombres, no de tipos: renombrar la local, la captura o el parametro sin cambiar la declaracion exterior"],
    ["el compilador no permite sombrear en Zig: cada nombre visible debe ser unico en su cadena de ambitos"],
    ["error: local constant shadows declaration of 'limite'",
     "error: local variable shadows declaration of 'cuenta'",
     "error: capture shadows declaration of 'x'",
     "error: function parameter shadows declaration of 'n'"],
    error_behavior="error de compilacion"))

# ---------------------------------------------------------------- sombreado de primitivos
ENTRIES.append(entry(
    "zig0.16/diag-shadow-primitive",
    "name shadows primitive: nombre de variable igual a un tipo primitivo",
    "Declarar una constante o variable con el nombre de un tipo primitivo (u8, i32, usize, bool...) hace que el compilador falle con 'name shadows primitive'. Solucion: usar otro nombre; si hace falta el nombre, escribirlo entre @\"...\".",
    ["name shadows primitive", "shadows primitive", "nombre sombrea primitivo", "u8 como nombre de variable", "variable llamada u8", "tipo primitivo como nombre", "@\"u8\"", "disambiguate primitive", "primitive name", "nombre de constante que sombrea un tipo primitivo", "sombrea un tipo primitivo", "llamar variable u8 o i32", "variable u8 o i32 en zig", "tipo primitivo como nombre"],
    '''const std = @import("std");

test "primitivo sombreado" {
    const u8 = 5;
    try std.testing.expectEqual(@as(u32, 5), u8);
}''',
    '''pub fn cincoDeBytes() u8 {
    const cinco: u8 = 5;
    return cinco;
}''',
    '''test "valor sin sombrear el tipo" {
    try std.testing.expectEqual(@as(u8, 5), cincoDeBytes());
}''',
    ["std.testing.expectEqual"],
    ["el nombre de un primitivo no es palabra reservada, pero el compilador no permite usarlo como identificador"],
    ["0.16: nombres de primitivos (u8, i32, usize...) no son identificadores validos en el mismo ambito"],
    ["error: name shadows primitive 'u8'"],
    error_behavior="error de compilacion"))

# ---------------------------------------------------------------- keyword comptime redundante
ENTRIES.append(entry(
    "zig0.16/diag-comptime-redundant",
    "comptime redundante: comptime dentro de un ambito ya comptime",
    "Dentro de un bloque comptime (o de una expresion comptime) la palabra comptime sobra: 'redundant comptime keyword in already comptime scope', 'comptime var is redundant in comptime scope' o 'comptime const is redundant'. Solucion: quitar el comptime interno o envolver solo la expresion de inicializacion.",
    ["redundant comptime keyword", "already comptime scope", "comptime var redundant", "comptime const redundant", "comptime redundante", "comptime dentro de comptime", "keyword comptime redundante", "is redundant in comptime scope", "wrap the initialization expression with comptime", "keyword comptime", "bloque comptime", "dentro de bloque comptime", "comptime redundante en bloque comptime"],
    '''const std = @import("std");

test "comptime anidado" {
    comptime {
        comptime {
            _ = 1;
        }
    }
}

test "comptime var redundante" {
    comptime {
        comptime var x: u32 = 1;
        x += 1;
    }
}

test "comptime const redundante" {
    comptime {
        comptime const x: u32 = 1;
        _ = x;
    }
}''',
    '''pub const DOS: u32 = blk: {
    var x: u32 = 1;
    x += 1;
    break :blk x;
};''',
    '''test "DOS vale dos" {
    try std.testing.expectEqual(@as(u32, 2), DOS);
}''',
    ["std.testing.expectEqual"],
    ["dentro de comptime todo ya es comptime: no repetir la palabra; en una constante de nivel superior basta con el bloque etiquetado"],
    ["0.16: el compilador rechaza comptime repetido en ambitos comptime (error, no advertencia)"],
    ["error: redundant comptime keyword in already comptime scope",
     "error: 'comptime var' is redundant in comptime scope",
     "error: 'comptime const' is redundant; instead wrap the initialization expression with 'comptime'"],
    error_behavior="error de compilacion"))

# ---------------------------------------------------------------- inline redundante
ENTRIES.append(entry(
    "zig0.16/diag-inline-redundant",
    "inline redundante dentro de un ambito comptime",
    "Dentro de un bloque comptime, un bucle no necesita (ni admite) la palabra inline: el compilador falla con 'redundant inline keyword in comptime scope'. Solucion: quitar inline; el bucle comptime ya se evalua en compilacion.",
    ["redundant inline keyword", "inline keyword in comptime scope", "inline for dentro de comptime", "inline while comptime", "inline redundante", "inline sobra en comptime", "comptime scope inline", "inline for", "inline dentro de comptime", "inline for dentro de comptime", "redundante en comptime"],
    '''const std = @import("std");

test "inline redundante" {
    comptime {
        inline for (0..2) |i| _ = i;
    }
}''',
    '''pub fn sumaDos() usize {
    var s: usize = 0;
    for (0..2) |i| s += i;
    return s;
}''',
    '''test "sumaDos suma 0 y 1" {
    try std.testing.expectEqual(@as(usize, 1), sumaDos());
}''',
    ["std.testing.expectEqual"],
    ["el bloque comptime ya fuerza la evaluacion; inline solo tiene sentido en codigo de runtime"],
    ["0.16: inline dentro de comptime es error de compilacion"],
    ["error: redundant inline keyword in comptime scope"],
    error_behavior="error de compilacion"))

# ---------------------------------------------------------------- valor de runtime donde se requiere comptime
ENTRIES.append(entry(
    "zig0.16/diag-comptime-runtime-value",
    "unable to resolve comptime value: valor de runtime donde se exige comptime",
    "Un tipo o tamano (p. ej. la longitud de un array) necesita un valor conocido en compilacion y se usa una variable que cambia en runtime: el compilador falla con 'unable to resolve comptime value' y 'types must be comptime-known'. Solucion: usar una constante comptime o un slice dinamico.",
    ["unable to resolve comptime value", "types must be comptime-known", "comptime-known", "valor de runtime en comptime", "longitud de array no conocida en compilacion", "array size runtime", "tamano de array variable", "comptime value unresolved", "comptime keyword forces comptime evaluation", "tamano de array en comptime", "variable de runtime en comptime", "longitud conocida en compilacion", "valor cambia en ejecucion", "array de tamano variable", "longitud de array"],
    '''const std = @import("std");

test "longitud en comptime" {
    var n: usize = 4;
    n += 1;
    const arr: [n]u8 = undefined;
    try std.testing.expectEqual(@as(usize, 5), arr.len);
}''',
    '''pub fn longitudFija() usize {
    const n: usize = 5;
    const arr: [n]u8 = undefined;
    return arr.len;
}''',
    '''test "longitud fija" {
    try std.testing.expectEqual(@as(usize, 5), longitudFija());
}''',
    ["std.testing.expectEqual"],
    ["si el tamano depende de la ejecucion, usar un slice o std.ArrayList en lugar de un array de tamano comptime"],
    ["en Zig el tamano de un array es parte del tipo: debe ser conocido al compilar"],
    ["error: unable to resolve comptime value"],
    error_behavior="error de compilacion"))

# ---------------------------------------------------------------- llamada de runtime dentro de comptime
ENTRIES.append(entry(
    "zig0.16/diag-comptime-runtime-call",
    "unable to evaluate comptime expression: llamada de runtime dentro de comptime",
    "Dentro de comptime se llama una funcion que toca el sistema (syscall, reloj, archivos, proceso): el compilador falla con 'unable to evaluate comptime expression' y 'operation is runtime due to this operand'. Solucion: quitar comptime de esa llamada y calcular en runtime.",
    ["unable to evaluate comptime expression", "operation is runtime due to this operand", "called at comptime from here", "llamada runtime en comptime", "syscall en comptime", "pid en comptime", "getpid comptime", "no puedo evaluar en compilacion", "evaluacion comptime fallida", "syscall dentro de comptime", "funcion que hace syscall", "llamada a sistema en comptime", "depende del sistema operativo", "sistema operativo en comptime"],
    '''const std = @import("std");

fn pidActual() u32 {
    return @intCast(std.os.linux.getpid());
}

test "pid en comptime" {
    const pid = comptime pidActual();
    try std.testing.expect(pid > 0);
}''',
    '''pub fn pidActual() u32 {
    return @intCast(std.os.linux.getpid());
}''',
    '''test "pid en runtime es positivo" {
    try std.testing.expect(pidActual() > 0);
}''',
    ["std.os.linux.getpid"],
    ["solo es comptime lo que no depende del entorno: syscalls, reloj, archivos y procesos se llaman en runtime"],
    ["comptime obliga a evaluar al compilar; las funciones que hacen syscalls no se pueden evaluar ahi"],
    ["error: unable to evaluate comptime expression"],
    error_behavior="error de compilacion"))

# ---------------------------------------------------------------- @ptrCast descarta const
ENTRIES.append(entry(
    "zig0.16/diag-ptrcast-const",
    "@ptrCast discards const qualifier: quitar const con un cast",
    "Convertir un puntero *const T a *T con @ptrCast falla con '@ptrCast discards const qualifier'. Solucion correcta: declarar el parametro o la variable con el tipo const que corresponde (*const T). @constCast solo sirve si la memoria es realmente mutable; escribir en memoria const es comportamiento indefinido.",
    ["@ptrCast discards const qualifier", "discards const qualifier", "ptrCast const", "@constCast", "quitar const puntero", "puntero const a mutable", "use @constCast to discard const qualifier", "descarta const", "const qualifier", "puntero const", "puntero mutable", "convertir puntero const a mutable", "const a mutable", "quitar const"],
    '''const std = @import("std");

test "ptrcast quita const" {
    const x: u8 = 1;
    const p: *u8 = @ptrCast(&x);
    try std.testing.expectEqual(@as(u8, 1), p.*);
}''',
    '''pub fn valorDe(x: *const u8) u8 {
    const p: *const u8 = x;
    return p.*;
}''',
    '''test "valorDe lee sin quitar const" {
    const x: u8 = 1;
    try std.testing.expectEqual(@as(u8, 1), valorDe(&x));
}''',
    ["std.testing.expectEqual"],
    ["@constCast no es un arreglo: si la memoria es const, escribir en ella es comportamiento indefinido; usar tipos const correctos"],
    ["0.16: @ptrCast no cambia la constness del puntero; el compilador exige @constCast explicito"],
    ["error: @ptrCast discards const qualifier"],
    error_behavior="error de compilacion"))

# ---------------------------------------------------------------- estrechamiento de enteros
ENTRIES.append(entry(
    "zig0.16/diag-narrowing-intcast",
    "expected type uN found uM: estrechar un entero (intCast/truncate)",
    "Asignar un entero de mas bits a uno de menos bits (u32 a u8) falla con 'expected type u8, found u32', porque Zig no convierte en silencio. Hay que elegir la conversion explicita: @truncate (conserva los bits bajos y descarta el resto sin aviso), @intCast (verifica el rango en Debug y ReleaseSafe y panica si no cabe) o std.math.cast (devuelve null si no cabe).",
    ["expected type u8 found u32", "expected type", "found u32", "cannot represent all possible", "truncate", "intCast", "estrechar entero", "u32 a u8", "conversion de entero", "@truncate", "@intCast", "tipo entero incompatible", "unsigned 8-bit int cannot represent", "estrechar un entero", "u32 a u8", "variable u8 da error de tipo", "dar error de tipo", "entero de mas bits", "pasar u32 a u8"],
    '''const std = @import("std");

fn convierte(a: u32) u8 {
    const b: u8 = a;
    return b;
}

test "estrechar" {
    try std.testing.expectEqual(@as(u8, 44), convierte(300));
}''',
    '''pub fn bajoBits(a: u32) u8 {
    return @truncate(a);
}''',
    '''test "bajoBits conserva los 8 bits bajos" {
    try std.testing.expectEqual(@as(u8, 44), bajoBits(300));
}''',
    ["std.testing.expectEqual", "@truncate"],
    ["elegir segun la intencion: @truncate descarta bits altos en silencio (300 -> 44); @intCast verifica el rango y panica si no cabe; std.math.cast devuelve null"],
    ["0.16: asignacion implicita entre enteros de distinto ancho es error; la conversion debe ser explicita"],
    ["error: expected type 'u8', found 'u32'"],
    error_behavior="error de compilacion; con @intCast el fallo en runtime es panico en Debug/ReleaseSafe"))

# ---------------------------------------------------------------- builtin sin importar
ENTRIES.append(entry(
    "zig0.16/diag-builtin-undeclared",
    "use of undeclared identifier builtin: falta importar builtin",
    "Usar builtin.os, builtin.mode u otro campo de la informacion de compilacion sin declararlo falla con 'use of undeclared identifier builtin'. Solucion: const builtin = @import(\"builtin\"); a nivel de fichero.",
    ["use of undeclared identifier builtin", "undeclared identifier 'builtin'", "falta const builtin", "@import builtin", "builtin.os", "builtin.mode", "identificador builtin no declarado", "importar builtin", "undeclared identifier", "no conoce builtin", "builtin sistema operativo", "como miro el sistema operativo", "sistema operativo builtin", "builtin.os.tag"],
    '''const std = @import("std");

test "plataforma" {
    try std.testing.expect(builtin.os.tag == .linux);
}''',
    '''const builtin = @import("builtin");

pub fn esLinux() bool {
    return builtin.os.tag == .linux;
}''',
    '''test "esLinux coincide con el sistema" {
    try std.testing.expectEqual(builtin.os.tag == .linux, esLinux());
}''',
    ["@import", "std.testing.expectEqual"],
    ["builtin no es global: hay que importarlo en cada fichero que lo use"],
    ["builtin describe la compilacion actual (os, mode, cpu); no cambia en runtime"],
    ["error: use of undeclared identifier 'builtin'"],
    error_behavior="error de compilacion"))

CONTRACTS = {e["operation_id"]: _c(None, None, None, [], **_SKIP) for e in ENTRIES}
