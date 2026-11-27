"""Recetas del area colecciones (dict, list, sorted, set, heapq, deque, Counter).

Cada zig_test fue ejecutado con `zig test` (0.16.0) y cada py_ref con python3."""

from pyzig.fuzz.contracts import CONTRACTS as _FUZZ, _c

ZIG = "0.16.0"; PY = "3.12"; PROV = "std local de zig 0.16.0 (repo en lib/std)"

ENTRIES = [
dict(operation_id="zig0.16/dict-str-int-basic",
    name='diccionario str->int (StringHashMap) get/put/contains/iteracion',
    intent='Usar un diccionario de claves string y valores enteros: insertar, leer con valor por defecto, comprobar pertenencia, acumular, borrar e iterar.',
    aliases=['dict', 'dict.get', 'dict.setdefault', 'd[k] = v', 'key in d', 'dict.pop', 'dict.items', 'hash map', 'mapa clave valor', 'diccionario de cadenas a enteros', 'StringHashMap', 'contar con diccionario', 'valor por defecto si no existe', 'comprobar si existe una clave', 'contador por clave'],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''d = {}
d["a"] = 1
d["a"] = 10
print(d.get("a"), "a" in d, "zzz" in d, len(d))
print(d.get("x", -1))
d["hits"] = d.get("hits", 0) + 1
try:
    d["nope"]
except KeyError:
    print("KeyError")
print(d.pop("a"), d.pop("a", None))
for k, v in d.items():
    print(k, v)''',
    zig_impl=r'''pub const Dict = std.StringHashMapUnmanaged(i64);

/// d[key] = d.get(key, 0) + delta
pub fn addTo(d: *Dict, gpa: std.mem.Allocator, key: []const u8, delta: i64) !void {
    const gop = try d.getOrPut(gpa, key);
    if (!gop.found_existing) gop.value_ptr.* = 0;
    gop.value_ptr.* += delta;
}

/// d.get(key, default)
pub fn getOr(d: *const Dict, key: []const u8, default: i64) i64 {
    return d.get(key) orelse default;
}

pub fn sumValues(d: *const Dict) i64 {
    var total: i64 = 0;
    var it = d.iterator();
    while (it.next()) |entry| total += entry.value_ptr.*;
    return total;
}''',
    zig_test=r'''const std = @import("std");

pub const Dict = std.StringHashMapUnmanaged(i64);

/// d[key] = d.get(key, 0) + delta
pub fn addTo(d: *Dict, gpa: std.mem.Allocator, key: []const u8, delta: i64) !void {
    const gop = try d.getOrPut(gpa, key);
    if (!gop.found_existing) gop.value_ptr.* = 0;
    gop.value_ptr.* += delta;
}

/// d.get(key, default)
pub fn getOr(d: *const Dict, key: []const u8, default: i64) i64 {
    return d.get(key) orelse default;
}

pub fn sumValues(d: *const Dict) i64 {
    var total: i64 = 0;
    var it = d.iterator();
    while (it.next()) |entry| total += entry.value_ptr.*;
    return total;
}

test "put get contains" {
    const gpa = std.testing.allocator;
    var d: Dict = .empty;
    defer d.deinit(gpa);
    try d.put(gpa, "a", 1);
    try d.put(gpa, "b", 2);
    try d.put(gpa, "a", 10); // sobrescribe
    try std.testing.expectEqual(@as(?i64, 10), d.get("a"));
    try std.testing.expect(d.contains("b"));
    try std.testing.expect(!d.contains("zzz"));
    try std.testing.expectEqual(@as(u32, 2), d.count());
}

test "get con valor por defecto y claves ausentes" {
    const gpa = std.testing.allocator;
    var d: Dict = .empty;
    defer d.deinit(gpa);
    try std.testing.expectEqual(@as(i64, -1), getOr(&d, "x", -1));
    try d.put(gpa, "x", 5);
    try std.testing.expectEqual(@as(i64, 5), getOr(&d, "x", -1));
    // d["x"] en Python lanza KeyError; aqui get devuelve null
    try std.testing.expect(d.get("nope") == null);
}

test "addTo acumula (d[k] = d.get(k, 0) + n)" {
    const gpa = std.testing.allocator;
    var d: Dict = .empty;
    defer d.deinit(gpa);
    try addTo(&d, gpa, "hits", 1);
    try addTo(&d, gpa, "hits", 2);
    try addTo(&d, gpa, "miss", -4);
    try std.testing.expectEqual(@as(i64, 3), getOr(&d, "hits", 0));
    try std.testing.expectEqual(@as(i64, -4), getOr(&d, "miss", 0));
    try std.testing.expectEqual(@as(i64, -1), sumValues(&d));
}

test "remove devuelve false si no existe y fetchRemove da el valor (pop)" {
    const gpa = std.testing.allocator;
    var d: Dict = .empty;
    defer d.deinit(gpa);
    try d.put(gpa, "k", 7);
    try std.testing.expect(!d.remove("otra"));
    const kv = d.fetchRemove("k").?;
    try std.testing.expectEqual(@as(i64, 7), kv.value);
    try std.testing.expect(d.fetchRemove("k") == null);
    try std.testing.expectEqual(@as(u32, 0), d.count());
}

test "iteracion visita todas las entradas (orden no garantizado)" {
    const gpa = std.testing.allocator;
    var d: Dict = .empty;
    defer d.deinit(gpa);
    const keys = [_][]const u8{ "uno", "dos", "tres", "cuatro" };
    for (keys, 1..) |k, i| try d.put(gpa, k, @intCast(i));
    var seen: usize = 0;
    var it = d.iterator();
    while (it.next()) |e| {
        seen += 1;
        try std.testing.expect(d.contains(e.key_ptr.*));
    }
    try std.testing.expectEqual(@as(usize, 4), seen);
    try std.testing.expectEqual(@as(i64, 10), sumValues(&d));
}''',
    apis_used=['std.StringHashMapUnmanaged', 'HashMapUnmanaged.put', 'HashMapUnmanaged.get', 'HashMapUnmanaged.getOrPut', 'HashMapUnmanaged.contains', 'HashMapUnmanaged.remove', 'HashMapUnmanaged.fetchRemove', 'HashMapUnmanaged.iterator', 'HashMapUnmanaged.deinit'],
    constraints=['std.StringHashMapUnmanaged: el allocator se pasa a cada put/getOrPut/deinit', 'las claves NO se copian: deben seguir vivas mientras el mapa las use'],
    preconditions=['las claves outlive al mapa (literales, arena o duplicadas por el llamador)'],
    postconditions=['get devuelve null para claves ausentes', 'tras put, contains(k) es true', 'count() refleja el numero de claves distintas'],
    side_effects=['asigna memoria en put/getOrPut'],
    error_behavior='put/getOrPut devuelven error.OutOfMemory; get/contains/remove no fallan (null/false si falta la clave).',
    ownership_memory='el mapa posee su tabla (deinit(gpa)); no posee las claves ni los valores.',
    differences=['Python lanza KeyError con d[k] ausente; Zig get devuelve ?i64 (null)', 'el orden de iteracion de Zig NO es el de insercion (Python 3.7+ si lo conserva)', 'las claves no se copian: Python mantiene la referencia al str, Zig solo guarda el slice', 'en 0.16 el StringHashMap gestionado sigue existiendo (init(allocator)); esta receta usa la variante Unmanaged con .empty', 'dict.pop(k) = fetchRemove(k) (devuelve ?KV); pop(k, default) = if (d.fetchRemove(k)) |kv| kv.value else default (fetchRemove(k) orelse default no compila: ?KV no es i64)', 'valores i64: el desbordamiento es ilegal en Debug (panic), no entero arbitrario como Python'],
    provenance=PROV),
dict(operation_id="zig0.16/list-append-pop-insert",
    name='lista dinamica: append, pop e insert (ArrayList unmanaged)',
    intent='Usar una lista que crece: anadir al final, sacar el ultimo o uno por indice (con negativos), insertar en una posicion con recorte como list.insert.',
    aliases=['list.append', 'list.pop', 'list.insert', 'list.extend', 'lista dinamica', 'vector que crece', 'ArrayList', 'anadir elemento a lista', 'quitar ultimo elemento', 'insertar en posicion', 'indice negativo', 'dynamic array', 'push back'],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''l = [10, 20, 30]
l.append(40); print(l.pop(), l)
l.insert(1, 15); l.insert(99, 99); l.insert(-100, 0); l.insert(-1, 77)
print(l)
print(l.pop(-1), l.pop(1))
try:
    [].pop()
except IndexError as e:
    print("IndexError", e)
try:
    [1].pop(5)
except IndexError as e:
    print("IndexError", e)''',
    zig_impl=r'''pub const List = std.ArrayList(i32);

pub const ListError = error{IndexOutOfRange};

/// lst.pop(index): index negativo cuenta desde el final; fuera de rango -> IndexOutOfRange.
pub fn popAt(l: *List, index: isize) ListError!i32 {
    const n: isize = @intCast(l.items.len);
    const i = if (index < 0) index + n else index;
    if (i < 0 or i >= n) return error.IndexOutOfRange;
    return l.orderedRemove(@intCast(i));
}

/// lst.insert(index, item): index negativo desde el final, y se recorta a [0, len] (como Python).
pub fn insertClamped(l: *List, gpa: std.mem.Allocator, index: isize, item: i32) !void {
    const n: isize = @intCast(l.items.len);
    var i = if (index < 0) index + n else index;
    if (i < 0) i = 0;
    if (i > n) i = n;
    try l.insert(gpa, @intCast(i), item);
}''',
    zig_test=r'''const std = @import("std");

pub const List = std.ArrayList(i32);

pub const ListError = error{IndexOutOfRange};

/// lst.pop(index): index negativo cuenta desde el final; fuera de rango -> IndexOutOfRange.
pub fn popAt(l: *List, index: isize) ListError!i32 {
    const n: isize = @intCast(l.items.len);
    const i = if (index < 0) index + n else index;
    if (i < 0 or i >= n) return error.IndexOutOfRange;
    return l.orderedRemove(@intCast(i));
}

/// lst.insert(index, item): index negativo desde el final, y se recorta a [0, len] (como Python).
pub fn insertClamped(l: *List, gpa: std.mem.Allocator, index: isize, item: i32) !void {
    const n: isize = @intCast(l.items.len);
    var i = if (index < 0) index + n else index;
    if (i < 0) i = 0;
    if (i > n) i = n;
    try l.insert(gpa, @intCast(i), item);
}

test "append y pop() del final" {
    const gpa = std.testing.allocator;
    var l: List = .empty;
    defer l.deinit(gpa);
    try l.append(gpa, 1);
    try l.append(gpa, 2);
    try l.appendSlice(gpa, &.{ 3, 4 });
    try std.testing.expectEqualSlices(i32, &.{ 1, 2, 3, 4 }, l.items);
    try std.testing.expectEqual(@as(?i32, 4), l.pop());
    try std.testing.expectEqual(@as(usize, 3), l.items.len);
}

test "pop sobre lista vacia devuelve null (Python lanza IndexError)" {
    const gpa = std.testing.allocator;
    var l: List = .empty;
    defer l.deinit(gpa);
    try std.testing.expect(l.pop() == null);
    try std.testing.expectError(error.IndexOutOfRange, popAt(&l, 0));
}

test "insert en medio, al inicio y recortado" {
    const gpa = std.testing.allocator;
    var l: List = .empty;
    defer l.deinit(gpa);
    try l.appendSlice(gpa, &.{ 10, 20, 30 });
    try insertClamped(&l, gpa, 1, 15);
    try insertClamped(&l, gpa, 0, 5);
    try insertClamped(&l, gpa, 99, 99); // > len -> al final
    try insertClamped(&l, gpa, -100, 0); // muy negativo -> al inicio
    try insertClamped(&l, gpa, -1, 77); // antes del ultimo
    try std.testing.expectEqualSlices(i32, &.{ 0, 5, 10, 15, 20, 30, 77, 99 }, l.items);
}

test "popAt con indice negativo y fuera de rango" {
    const gpa = std.testing.allocator;
    var l: List = .empty;
    defer l.deinit(gpa);
    try l.appendSlice(gpa, &.{ 1, 2, 3, 4 });
    try std.testing.expectEqual(@as(i32, 2), try popAt(&l, 1));
    try std.testing.expectEqual(@as(i32, 4), try popAt(&l, -1));
    try std.testing.expectError(error.IndexOutOfRange, popAt(&l, 2));
    try std.testing.expectError(error.IndexOutOfRange, popAt(&l, -3));
    try std.testing.expectEqualSlices(i32, &.{ 1, 3 }, l.items);
}

test "toOwnedSlice entrega la memoria al llamador" {
    const gpa = std.testing.allocator;
    var l: List = .empty;
    try l.appendSlice(gpa, &.{ 7, 8 });
    const owned = try l.toOwnedSlice(gpa);
    defer gpa.free(owned);
    try std.testing.expectEqualSlices(i32, &.{ 7, 8 }, owned);
    try std.testing.expectEqual(@as(usize, 0), l.items.len);
}''',
    apis_used=['std.ArrayList', 'ArrayList.empty', 'ArrayList.append', 'ArrayList.appendSlice', 'ArrayList.pop', 'ArrayList.insert', 'ArrayList.orderedRemove', 'ArrayList.toOwnedSlice', 'ArrayList.deinit'],
    constraints=['en 0.16 std.ArrayList es la variante unmanaged: append/insert/deinit/toOwnedSlice reciben el allocator', 'orderedRemove asserta indice en rango: validar antes (popAt)'],
    preconditions=['gpa es el mismo allocator en todas las llamadas sobre la lista'],
    postconditions=['pop() devuelve ?T: null si esta vacia', 'insertClamped nunca falla por indice, solo por memoria', 'los items quedan en l.items (slice)'],
    side_effects=['asigna/realoja memoria'],
    error_behavior='append/insert/appendSlice: error.OutOfMemory; popAt: error.IndexOutOfRange; pop(): null si vacia.',
    ownership_memory='la lista posee su buffer (deinit(gpa)); toOwnedSlice transfiere la propiedad al llamador, que lo libera con gpa.free.',
    differences=['list.pop() sobre lista vacia lanza IndexError en Python; ArrayList.pop() devuelve null', 'ArrayList.orderedRemove(i) con i fuera de rango es comportamiento ilegal (panic en Debug); la receta valida y devuelve IndexOutOfRange', 'ArrayList.insert con indice > len es ilegal; Python lo recorta: la receta lo emula (insertClamped)', 'los indices negativos no existen en Zig (usize): la receta usa isize y suma len', 'punteros a items se invalidan tras append/insert si realoja', 'no existe ArrayList.init(allocator) en 0.16: usar .empty o initCapacity'],
    provenance=PROV),
dict(operation_id="zig0.16/sorted-key-stable",
    name='ordenar con clave y orden estable (sorted/list.sort)',
    intent='Ordenar una coleccion por una clave de forma estable, con reverse opcional, devolviendo una copia (sorted) o en sitio (list.sort).',
    aliases=['sorted', 'list.sort', 'sorted key=', 'key=lambda', 'reverse=True', 'orden estable', 'stable sort', 'ordenar por campo', 'ordenar lista de structs', 'std.mem.sort', 'ordenar cadenas', 'sort by key', 'ordenar por edad'],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''people = [("a", 2), ("b", 1), ("c", 2), ("d", 1), ("e", 2)]
print([n for n, _ in sorted(people, key=lambda p: p[1])])
print([n for n, _ in sorted(people, key=lambda p: p[1], reverse=True)])
print(sorted(["pera", "Zeta", "manzana", "", "ave"]))
people.sort(key=lambda p: p[1])   # en sitio, tambien estable''',
    zig_impl=r'''pub const Person = struct { name: []const u8, age: u32 };

fn ageAsc(_: void, a: Person, b: Person) bool {
    return a.age < b.age;
}

fn ageDesc(_: void, a: Person, b: Person) bool {
    return a.age > b.age;
}

/// sorted(items, key=lambda p: p.age, reverse=reverse): copia nueva y orden ESTABLE.
pub fn sortedByAge(gpa: std.mem.Allocator, items: []const Person, reverse: bool) ![]Person {
    const out = try gpa.dupe(Person, items);
    errdefer gpa.free(out);
    if (reverse) {
        std.mem.sort(Person, out, {}, ageDesc);
    } else {
        std.mem.sort(Person, out, {}, ageAsc);
    }
    return out;
}

fn strLess(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.lessThan(u8, a, b);
}

/// lst.sort() sobre strings, en sitio (orden por bytes UTF-8 = orden por code point).
pub fn sortStrings(items: [][]const u8) void {
    std.mem.sort([]const u8, items, {}, strLess);
}''',
    zig_test=r'''const std = @import("std");

pub const Person = struct { name: []const u8, age: u32 };

fn ageAsc(_: void, a: Person, b: Person) bool {
    return a.age < b.age;
}

fn ageDesc(_: void, a: Person, b: Person) bool {
    return a.age > b.age;
}

/// sorted(items, key=lambda p: p.age, reverse=reverse): copia nueva y orden ESTABLE.
pub fn sortedByAge(gpa: std.mem.Allocator, items: []const Person, reverse: bool) ![]Person {
    const out = try gpa.dupe(Person, items);
    errdefer gpa.free(out);
    if (reverse) {
        std.mem.sort(Person, out, {}, ageDesc);
    } else {
        std.mem.sort(Person, out, {}, ageAsc);
    }
    return out;
}

fn strLess(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.lessThan(u8, a, b);
}

/// lst.sort() sobre strings, en sitio (orden por bytes UTF-8 = orden por code point).
pub fn sortStrings(items: [][]const u8) void {
    std.mem.sort([]const u8, items, {}, strLess);
}

test "orden ascendente por clave" {
    const gpa = std.testing.allocator;
    const in = [_]Person{ .{ .name = "ana", .age = 30 }, .{ .name = "bob", .age = 20 }, .{ .name = "cy", .age = 25 } };
    const out = try sortedByAge(gpa, &in, false);
    defer gpa.free(out);
    try std.testing.expectEqualStrings("bob", out[0].name);
    try std.testing.expectEqualStrings("cy", out[1].name);
    try std.testing.expectEqualStrings("ana", out[2].name);
    // el original no cambia
    try std.testing.expectEqualStrings("ana", in[0].name);
}

test "estabilidad: claves iguales conservan el orden original" {
    const gpa = std.testing.allocator;
    const in = [_]Person{
        .{ .name = "a", .age = 2 }, .{ .name = "b", .age = 1 }, .{ .name = "c", .age = 2 },
        .{ .name = "d", .age = 1 }, .{ .name = "e", .age = 2 },
    };
    const asc = try sortedByAge(gpa, &in, false);
    defer gpa.free(asc);
    const names_asc = [_][]const u8{ "b", "d", "a", "c", "e" };
    for (asc, names_asc) |p, n| try std.testing.expectEqualStrings(n, p.name);
    // reverse=True de Python tambien conserva el orden original entre iguales
    const desc = try sortedByAge(gpa, &in, true);
    defer gpa.free(desc);
    const names_desc = [_][]const u8{ "a", "c", "e", "b", "d" };
    for (desc, names_desc) |p, n| try std.testing.expectEqualStrings(n, p.name);
}

test "lista vacia y de un elemento" {
    const gpa = std.testing.allocator;
    const e = try sortedByAge(gpa, &.{}, false);
    defer gpa.free(e);
    try std.testing.expectEqual(@as(usize, 0), e.len);
    const one = try sortedByAge(gpa, &.{.{ .name = "x", .age = 1 }}, true);
    defer gpa.free(one);
    try std.testing.expectEqual(@as(usize, 1), one.len);
}

test "sort de strings por bytes (mayusculas antes que minusculas)" {
    var arr = [_][]const u8{ "pera", "Zeta", "manzana", "", "ave" };
    sortStrings(&arr);
    const want = [_][]const u8{ "", "Zeta", "ave", "manzana", "pera" };
    for (arr, want) |a, w| try std.testing.expectEqualStrings(w, a);
}''',
    apis_used=['std.mem.sort', 'std.sort.block', 'std.mem.lessThan', 'std.mem.Allocator.dupe'],
    constraints=['std.mem.sort es estable (block sort); std.mem.sortUnstable (pdq) NO lo es', 'la funcion lessThan debe ser un orden estricto (a < b, nunca <=)'],
    preconditions=['el comparador es comptime-known'],
    postconditions=['claves iguales conservan el orden relativo original', 'sortedByAge no modifica la entrada'],
    side_effects=['sortedByAge asigna una copia; sortStrings ordena en sitio'],
    error_behavior='sortedByAge: error.OutOfMemory; el sort en si no falla.',
    ownership_memory='sortedByAge devuelve un slice que el llamador libera con gpa.free; sortStrings no asigna.',
    differences=['Python key= se evalua una vez por elemento; el comparador Zig se evalua en cada comparacion (precalcular la clave si es cara)', 'reverse=True de Python conserva el orden original de los iguales; invertir el comparador (a.k > b.k) da el mismo resultado, NO invertir la lista ordenada', 'std.mem.lessThan compara bytes UTF-8: coincide con code points de Python, no con ordenacion locale', 'floats con NaN: el comparador no es un orden total (Python tampoco lo garantiza)', 'list.sort() en sitio = std.mem.sort sobre el slice; sorted() = dupe + sort', 'std.mem.sortUnstable es mas rapido pero no estable: no usarlo si importa el orden de los iguales'],
    provenance=PROV),
dict(operation_id="zig0.16/set-str-membership",
    name='conjunto de strings (set) con add/discard/in/union/interseccion',
    intent='Mantener un conjunto de cadenas sin duplicados: anadir, quitar, comprobar pertenencia, unir e intersectar.',
    aliases=['set', 'set.add', 'set.discard', 'set.remove', 'x in set', 'set union', 'set intersection', 'a | b', 'a & b', 'conjunto sin duplicados', 'deduplicar strings', 'HashSet', 'StringHashMap void'],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''s = set()
print(s.add("a"))
s.add("a")
print("a" in s, len(s))
s.discard("zz")
try:
    s.remove("zz")
except KeyError:
    print("KeyError")
a, b = {"x", "y", "z"}, {"y", "z", "w"}
print(len(a & b)); a |= b; print(len(a))
print("" in set(), "" in {""})''',
    zig_impl=r'''pub const StrSet = std.StringHashMapUnmanaged(void);

/// s.add(x); devuelve true si era nuevo (Python devuelve None).
/// La clave NO se copia: el llamador debe mantenerla viva.
pub fn add(s: *StrSet, gpa: std.mem.Allocator, key: []const u8) !bool {
    const gop = try s.getOrPut(gpa, key);
    return !gop.found_existing;
}

/// s.discard(x): no falla si no existe; devuelve si estaba.
pub fn discard(s: *StrSet, key: []const u8) bool {
    return s.remove(key);
}

/// len(a & b)
pub fn intersectionCount(a: *const StrSet, b: *const StrSet) usize {
    var n: usize = 0;
    var it = a.keyIterator();
    while (it.next()) |k| {
        if (b.contains(k.*)) n += 1;
    }
    return n;
}

/// a |= b
pub fn unionInto(a: *StrSet, gpa: std.mem.Allocator, b: *const StrSet) !void {
    var it = b.keyIterator();
    while (it.next()) |k| _ = try add(a, gpa, k.*);
}''',
    zig_test=r'''const std = @import("std");

pub const StrSet = std.StringHashMapUnmanaged(void);

/// s.add(x); devuelve true si era nuevo (Python devuelve None).
/// La clave NO se copia: el llamador debe mantenerla viva.
pub fn add(s: *StrSet, gpa: std.mem.Allocator, key: []const u8) !bool {
    const gop = try s.getOrPut(gpa, key);
    return !gop.found_existing;
}

/// s.discard(x): no falla si no existe; devuelve si estaba.
pub fn discard(s: *StrSet, key: []const u8) bool {
    return s.remove(key);
}

/// len(a & b)
pub fn intersectionCount(a: *const StrSet, b: *const StrSet) usize {
    var n: usize = 0;
    var it = a.keyIterator();
    while (it.next()) |k| {
        if (b.contains(k.*)) n += 1;
    }
    return n;
}

/// a |= b
pub fn unionInto(a: *StrSet, gpa: std.mem.Allocator, b: *const StrSet) !void {
    var it = b.keyIterator();
    while (it.next()) |k| _ = try add(a, gpa, k.*);
}

test "add, in y len" {
    const gpa = std.testing.allocator;
    var s: StrSet = .empty;
    defer s.deinit(gpa);
    try std.testing.expect(try add(&s, gpa, "a"));
    try std.testing.expect(try add(&s, gpa, "b"));
    try std.testing.expect(!(try add(&s, gpa, "a"))); // duplicado
    try std.testing.expect(s.contains("a"));
    try std.testing.expect(!s.contains("c"));
    try std.testing.expectEqual(@as(u32, 2), s.count());
}

test "discard no falla con ausentes (remove de Python si)" {
    const gpa = std.testing.allocator;
    var s: StrSet = .empty;
    defer s.deinit(gpa);
    _ = try add(&s, gpa, "x");
    try std.testing.expect(discard(&s, "x"));
    try std.testing.expect(!discard(&s, "x"));
    try std.testing.expectEqual(@as(u32, 0), s.count());
}

test "interseccion y union" {
    const gpa = std.testing.allocator;
    var a: StrSet = .empty;
    defer a.deinit(gpa);
    var b: StrSet = .empty;
    defer b.deinit(gpa);
    for ([_][]const u8{ "x", "y", "z" }) |k| _ = try add(&a, gpa, k);
    for ([_][]const u8{ "y", "z", "w" }) |k| _ = try add(&b, gpa, k);
    try std.testing.expectEqual(@as(usize, 2), intersectionCount(&a, &b));
    try unionInto(&a, gpa, &b);
    try std.testing.expectEqual(@as(u32, 4), a.count());
    try std.testing.expect(a.contains("w"));
}

test "conjunto vacio y cadena vacia como elemento" {
    const gpa = std.testing.allocator;
    var s: StrSet = .empty;
    defer s.deinit(gpa);
    try std.testing.expect(!s.contains(""));
    try std.testing.expect(try add(&s, gpa, ""));
    try std.testing.expect(s.contains(""));
}''',
    apis_used=['std.StringHashMapUnmanaged(void)', 'HashMapUnmanaged.getOrPut', 'HashMapUnmanaged.contains', 'HashMapUnmanaged.remove', 'HashMapUnmanaged.keyIterator', 'HashMapUnmanaged.count'],
    constraints=['std no tiene un tipo Set de strings: se usa un mapa con valor void', 'las claves no se copian: deben seguir vivas'],
    preconditions=['claves outlive al conjunto'],
    postconditions=['add devuelve true solo si el elemento era nuevo', 'discard nunca falla'],
    side_effects=['asigna memoria en add/unionInto'],
    error_behavior='add/unionInto: error.OutOfMemory; discard/contains no fallan.',
    ownership_memory='el conjunto posee su tabla (deinit(gpa)); no posee las claves.',
    differences=['set.add devuelve None en Python; aqui devuelve bool (nuevo o no)', 'set.remove lanza KeyError si falta; aqui remove devuelve false (equivale a discard)', 'orden de iteracion indefinido en ambos, pero distinto entre si', 'las claves no se copian: si el buffer de origen se libera, el conjunto queda con punteros colgantes', 'no hay operadores | & -: se escriben con iteracion (unionInto, intersectionCount)', 'comparacion por bytes, sin normalizacion unicode (igual que Python str, que compara code points)'],
    provenance=PROV),
dict(operation_id="zig0.16/heapq-priority-queue",
    name='cola de prioridad / heapq (std.PriorityQueue)',
    intent='Mantener una cola donde se extrae siempre el elemento de menor prioridad (heapq.heappush/heappop), con desempate por orden de insercion.',
    aliases=['heapq', 'heapq.heappush', 'heapq.heappop', 'heapq.heapify', 'heap[0]', 'priority queue', 'cola de prioridad', 'min-heap', 'montículo', 'PriorityQueue', 'queue.PriorityQueue', 'max heap', 'extraer el menor'],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''import heapq
h = []
for x in [5, 1, 8, 3, 1]:
    heapq.heappush(h, x)
print(h[0], [heapq.heappop(h) for _ in range(5)])
try:
    heapq.heappop([])
except IndexError as e:
    print("IndexError", e)
q = []
for i, (p, n) in enumerate([(2, "b"), (1, "a"), (2, "c"), (1, "d")]):
    heapq.heappush(q, (p, i, n))
print([heapq.heappop(q)[2] for _ in range(4)])
m = [9, 4, 7, 1, 6]; heapq.heapify(m); print(heapq.heappop(m), heapq.heappop(m))''',
    zig_impl=r'''pub const Task = struct { prio: u32, seq: u32, name: []const u8 };

/// Min-heap por (prio, seq): seq desempata, como (prio, contador, item) en heapq.
fn taskOrder(_: void, a: Task, b: Task) std.math.Order {
    const by_prio = std.math.order(a.prio, b.prio);
    if (by_prio != .eq) return by_prio;
    return std.math.order(a.seq, b.seq);
}

pub const TaskQueue = std.PriorityQueue(Task, void, taskOrder);

pub fn intMin(_: void, a: i32, b: i32) std.math.Order {
    return std.math.order(a, b);
}

pub const IntHeap = std.PriorityQueue(i32, void, intMin);''',
    zig_test=r'''const std = @import("std");

pub const Task = struct { prio: u32, seq: u32, name: []const u8 };

/// Min-heap por (prio, seq): seq desempata, como (prio, contador, item) en heapq.
fn taskOrder(_: void, a: Task, b: Task) std.math.Order {
    const by_prio = std.math.order(a.prio, b.prio);
    if (by_prio != .eq) return by_prio;
    return std.math.order(a.seq, b.seq);
}

pub const TaskQueue = std.PriorityQueue(Task, void, taskOrder);

pub fn intMin(_: void, a: i32, b: i32) std.math.Order {
    return std.math.order(a, b);
}

pub const IntHeap = std.PriorityQueue(i32, void, intMin);

test "heappush / heappop devuelven el menor" {
    const gpa = std.testing.allocator;
    var h: IntHeap = .empty;
    defer h.deinit(gpa);
    for ([_]i32{ 5, 1, 8, 3, 1 }) |x| try h.push(gpa, x);
    try std.testing.expectEqual(@as(?i32, 1), h.peek()); // heap[0]
    const want = [_]i32{ 1, 1, 3, 5, 8 };
    for (want) |w| try std.testing.expectEqual(@as(?i32, w), h.pop());
}

test "pop en heap vacio devuelve null (heappop lanza IndexError)" {
    const gpa = std.testing.allocator;
    var h: IntHeap = .empty;
    defer h.deinit(gpa);
    try std.testing.expect(h.pop() == null);
    try std.testing.expect(h.peek() == null);
    try std.testing.expectEqual(@as(usize, 0), h.count());
}

test "tuplas (prio, seq, nombre) desempatan por orden de insercion" {
    const gpa = std.testing.allocator;
    var q: TaskQueue = .empty;
    defer q.deinit(gpa);
    try q.push(gpa, .{ .prio = 2, .seq = 0, .name = "b" });
    try q.push(gpa, .{ .prio = 1, .seq = 1, .name = "a" });
    try q.push(gpa, .{ .prio = 2, .seq = 2, .name = "c" });
    try q.push(gpa, .{ .prio = 1, .seq = 3, .name = "d" });
    const want = [_][]const u8{ "a", "d", "b", "c" };
    for (want) |w| try std.testing.expectEqualStrings(w, q.pop().?.name);
}

test "heapify desde un slice propio (fromOwnedSlice)" {
    const gpa = std.testing.allocator;
    const buf = try gpa.dupe(i32, &.{ 9, 4, 7, 1, 6 });
    var h = IntHeap.fromOwnedSlice(buf, {});
    defer h.deinit(gpa);
    try std.testing.expectEqual(@as(?i32, 1), h.pop());
    try std.testing.expectEqual(@as(?i32, 4), h.pop());
    try std.testing.expectEqual(@as(usize, 3), h.count());
}

test "max-heap invirtiendo el orden" {
    const S = struct {
        fn maxOrder(_: void, a: i32, b: i32) std.math.Order {
            return std.math.order(b, a);
        }
    };
    const gpa = std.testing.allocator;
    var h: std.PriorityQueue(i32, void, S.maxOrder) = .empty;
    defer h.deinit(gpa);
    for ([_]i32{ 2, 9, 4 }) |x| try h.push(gpa, x);
    try std.testing.expectEqual(@as(?i32, 9), h.pop());
}''',
    apis_used=['std.PriorityQueue', 'PriorityQueue.empty', 'PriorityQueue.push', 'PriorityQueue.pop', 'PriorityQueue.peek', 'PriorityQueue.count', 'PriorityQueue.fromOwnedSlice', 'PriorityQueue.deinit', 'std.math.order'],
    constraints=['el comparador devuelve std.math.Order: .lt significa que el 2do argumento sale antes que el 3ro', 'en 0.16 se usa .empty y push(gpa, x) (no init(allocator)/add)'],
    preconditions=['el comparador define un orden total'],
    postconditions=['pop devuelve el elemento minimo segun el comparador', 'peek no lo extrae'],
    side_effects=['asigna memoria en push'],
    error_behavior='push: error.OutOfMemory; pop/peek devuelven null si esta vacia.',
    ownership_memory='la cola posee su buffer (deinit(gpa)); fromOwnedSlice toma posesion de un slice alocado con gpa.',
    differences=['heappop de lista vacia lanza IndexError; pop() devuelve null', 'heapq opera sobre una lista; PriorityQueue es un tipo aparte (los items son .items, sin orden de prioridad salvo [0])', 'ni heapq ni PriorityQueue son estables: el desempate se logra con un contador seq en la clave (como (prio, contador, item))', 'heapq es solo min-heap; para max-heap invierte el comparador (aqui) o niega las claves (Python)', 'heapq.nsmallest/nlargest/merge no existen en std', 'fromOwnedSlice es el equivalente de heapify pero consume el slice'],
    provenance=PROV),
dict(operation_id="zig0.16/deque-popleft-appendleft",
    name='cola doble (collections.deque) con maxlen y rotate',
    intent='Usar una cola de dos extremos: anadir/sacar por ambos lados en O(1), ventana deslizante con maxlen y rotacion.',
    aliases=['collections.deque', 'deque.append', 'deque.appendleft', 'deque.popleft', 'deque.pop', 'deque(maxlen=)', 'deque.rotate', 'cola doble', 'ring buffer', 'buffer circular', 'queue FIFO', 'ventana deslizante', 'double-ended queue', 'std.Deque'],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''from collections import deque
d = deque([2, 3]); d.appendleft(1)
print(d.popleft(), d.pop(), d[0], d[-1])
try:
    deque().popleft()
except IndexError as e:
    print("IndexError", e)
w = deque(maxlen=3)
for x in range(1, 6): w.append(x)
print(list(w))
z = deque(maxlen=0); z.append(9); print(len(z))
r = deque([1, 2, 3, 4, 5]); r.rotate(2); print(list(r)); r.rotate(-2); print(list(r))''',
    zig_impl=r'''pub const IntDeque = std.Deque(i32);

/// d = deque(maxlen=N); d.append(x): al llenarse descarta el elemento mas antiguo (frente).
pub fn appendMaxlen(d: *IntDeque, gpa: std.mem.Allocator, maxlen: usize, x: i32) !void {
    if (maxlen == 0) return;
    if (d.len >= maxlen) _ = d.popFront();
    try d.pushBack(gpa, x);
}

/// d.rotate(n): n > 0 rota a la derecha, n < 0 a la izquierda.
pub fn rotate(d: *IntDeque, n: isize) void {
    if (d.len < 2) return;
    const len: isize = @intCast(d.len);
    var k = @mod(n, len);
    // k pasos a la derecha: el ultimo pasa al frente. Siempre hay hueco tras popBack.
    while (k > 0) : (k -= 1) d.pushFrontAssumeCapacity(d.popBack().?);
}''',
    zig_test=r'''const std = @import("std");

pub const IntDeque = std.Deque(i32);

/// d = deque(maxlen=N); d.append(x): al llenarse descarta el elemento mas antiguo (frente).
pub fn appendMaxlen(d: *IntDeque, gpa: std.mem.Allocator, maxlen: usize, x: i32) !void {
    if (maxlen == 0) return;
    if (d.len >= maxlen) _ = d.popFront();
    try d.pushBack(gpa, x);
}

/// d.rotate(n): n > 0 rota a la derecha, n < 0 a la izquierda.
pub fn rotate(d: *IntDeque, n: isize) void {
    if (d.len < 2) return;
    const len: isize = @intCast(d.len);
    var k = @mod(n, len);
    // k pasos a la derecha: el ultimo pasa al frente. Siempre hay hueco tras popBack.
    while (k > 0) : (k -= 1) d.pushFrontAssumeCapacity(d.popBack().?);
}

test "append, appendleft, pop, popleft" {
    const gpa = std.testing.allocator;
    var d: IntDeque = .empty;
    defer d.deinit(gpa);
    try d.pushBack(gpa, 2);
    try d.pushBack(gpa, 3);
    try d.pushFront(gpa, 1);
    try std.testing.expectEqual(@as(usize, 3), d.len);
    try std.testing.expectEqual(@as(?i32, 1), d.popFront());
    try std.testing.expectEqual(@as(?i32, 3), d.popBack());
    try std.testing.expectEqual(@as(?i32, 2), d.front());
    try std.testing.expectEqual(@as(?i32, 2), d.back());
}

test "pop sobre deque vacio devuelve null (Python lanza IndexError)" {
    const gpa = std.testing.allocator;
    var d: IntDeque = .empty;
    defer d.deinit(gpa);
    try std.testing.expect(d.popFront() == null);
    try std.testing.expect(d.popBack() == null);
}

test "maxlen descarta por el frente" {
    const gpa = std.testing.allocator;
    var d: IntDeque = .empty;
    defer d.deinit(gpa);
    for ([_]i32{ 1, 2, 3, 4, 5 }) |x| try appendMaxlen(&d, gpa, 3, x);
    try std.testing.expectEqual(@as(usize, 3), d.len);
    var it = d.iterator();
    const want = [_]i32{ 3, 4, 5 };
    var i: usize = 0;
    while (it.next()) |v| : (i += 1) try std.testing.expectEqual(want[i], v);
    try std.testing.expectEqual(@as(usize, 3), i);
    // maxlen=0 no almacena nada
    var z: IntDeque = .empty;
    defer z.deinit(gpa);
    try appendMaxlen(&z, gpa, 0, 9);
    try std.testing.expectEqual(@as(usize, 0), z.len);
}

test "wrap-around del buffer circular conserva el orden logico" {
    const gpa = std.testing.allocator;
    var d = try IntDeque.initCapacity(gpa, 4);
    defer d.deinit(gpa);
    for ([_]i32{ 1, 2, 3, 4 }) |x| d.pushBackAssumeCapacity(x);
    _ = d.popFront();
    _ = d.popFront();
    d.pushBackAssumeCapacity(5);
    d.pushBackAssumeCapacity(6); // da la vuelta al buffer
    const want = [_]i32{ 3, 4, 5, 6 };
    for (want, 0..) |w, i| try std.testing.expectEqual(w, d.at(i));
}

test "rotate a derecha e izquierda" {
    const gpa = std.testing.allocator;
    var d: IntDeque = .empty;
    defer d.deinit(gpa);
    for ([_]i32{ 1, 2, 3, 4, 5 }) |x| try d.pushBack(gpa, x);
    rotate(&d, 2); // [4,5,1,2,3]
    try std.testing.expectEqual(@as(i32, 4), d.at(0));
    try std.testing.expectEqual(@as(i32, 3), d.at(4));
    rotate(&d, -2); // vuelve a [1,2,3,4,5]
    try std.testing.expectEqual(@as(i32, 1), d.at(0));
    try std.testing.expectEqual(@as(i32, 5), d.at(4));
}''',
    apis_used=['std.Deque', 'Deque.empty', 'Deque.initCapacity', 'Deque.pushBack', 'Deque.pushFront', 'Deque.pushBackAssumeCapacity', 'Deque.pushFrontAssumeCapacity', 'Deque.popFront', 'Deque.popBack', 'Deque.front', 'Deque.back', 'Deque.at', 'Deque.iterator', 'Deque.deinit'],
    constraints=['std.Deque existe en 0.16 como ring buffer creciente; las operaciones que crecen reciben gpa', 'maxlen no es parte del tipo: se emula con popFront antes de pushBack'],
    preconditions=['rotate: la cola no cambia de tamano, por eso AssumeCapacity es seguro tras popBack'],
    postconditions=['popFront/popBack devuelven null si esta vacia', 'len es el numero de elementos'],
    side_effects=['asigna memoria al crecer'],
    error_behavior='pushBack/pushFront: error.OutOfMemory; popFront/popBack: null si vacia.',
    ownership_memory='el deque posee su buffer (deinit(gpa)).',
    differences=['d[0] / d[-1] (leer extremos sin extraer) = d.front() / d.back(), que devuelven ?T; d.at(i) toma usize: sin indices negativos', 'deque.popleft() vacio lanza IndexError; popFront() devuelve null', 'deque(maxlen=N) es un tipo con limite; aqui el limite lo aplica appendMaxlen (nada impide pushBack directo)', 'd[i] de Python -> d.at(i), que asserta indice en rango', 'no hay insert/remove/index/extend sobre deque en std; solo extremos y iteracion', 'rotate(n) de Python acepta cualquier n; la receta usa @mod(n, len) y es O(n)', 'la iteracion con iterator() es de frente a final, sin mutar'],
    provenance=PROV),
dict(operation_id="zig0.16/counter-most-common",
    name='contador de frecuencias y most_common (collections.Counter)',
    intent='Contar ocurrencias de palabras y obtener las k mas frecuentes ordenadas de mayor a menor.',
    aliases=['collections.Counter', 'Counter.most_common', 'Counter(text.split())', 'contar palabras', 'frecuencia de palabras', 'word count', 'histograma de palabras', 'top k mas frecuentes', 'conteo de ocurrencias', 'frequency table', 'tokenize and count', 'cuantas veces aparece cada palabra', 'palabras mas repetidas'],
    source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
    py_ref=r'''from collections import Counter
c = Counter("a b a c b a".split())
print(c["a"], c["c"], c.most_common(2))
print(Counter("  \n".split()).most_common(5))
print(Counter("x y".split()).most_common(99))
print(Counter("pera manzana pera manzana kiwi".split()).most_common(3))
print(Counter()["ausente"])''',
    zig_impl=r'''pub const Counter = std.StringHashMapUnmanaged(usize);

pub const Count = struct { word: []const u8, n: usize };

/// Counter(text.split()): cuenta palabras separadas por espacios/tabs/saltos.
/// Las claves son subslices de `text` (no se copian): `text` debe seguir vivo.
pub fn countWords(gpa: std.mem.Allocator, text: []const u8) !Counter {
    var c: Counter = .empty;
    errdefer c.deinit(gpa);
    var it = std.mem.tokenizeAny(u8, text, " \t\r\n");
    while (it.next()) |w| {
        const gop = try c.getOrPut(gpa, w);
        if (!gop.found_existing) gop.value_ptr.* = 0;
        gop.value_ptr.* += 1;
    }
    return c;
}

fn moreCommon(_: void, a: Count, b: Count) bool {
    if (a.n != b.n) return a.n > b.n;
    return std.mem.lessThan(u8, a.word, b.word);
}

/// c.most_common(k): mayor a menor; empates por orden alfabetico (determinista).
pub fn mostCommon(gpa: std.mem.Allocator, c: *const Counter, k: usize) ![]Count {
    const all = try gpa.alloc(Count, c.count());
    errdefer gpa.free(all);
    var it = c.iterator();
    var i: usize = 0;
    while (it.next()) |e| : (i += 1) all[i] = .{ .word = e.key_ptr.*, .n = e.value_ptr.* };
    std.mem.sort(Count, all, {}, moreCommon);
    const take = @min(k, all.len);
    const out = try gpa.dupe(Count, all[0..take]);
    gpa.free(all);
    return out;
}''',
    zig_test=r'''const std = @import("std");

pub const Counter = std.StringHashMapUnmanaged(usize);

pub const Count = struct { word: []const u8, n: usize };

/// Counter(text.split()): cuenta palabras separadas por espacios/tabs/saltos.
/// Las claves son subslices de `text` (no se copian): `text` debe seguir vivo.
pub fn countWords(gpa: std.mem.Allocator, text: []const u8) !Counter {
    var c: Counter = .empty;
    errdefer c.deinit(gpa);
    var it = std.mem.tokenizeAny(u8, text, " \t\r\n");
    while (it.next()) |w| {
        const gop = try c.getOrPut(gpa, w);
        if (!gop.found_existing) gop.value_ptr.* = 0;
        gop.value_ptr.* += 1;
    }
    return c;
}

fn moreCommon(_: void, a: Count, b: Count) bool {
    if (a.n != b.n) return a.n > b.n;
    return std.mem.lessThan(u8, a.word, b.word);
}

/// c.most_common(k): mayor a menor; empates por orden alfabetico (determinista).
pub fn mostCommon(gpa: std.mem.Allocator, c: *const Counter, k: usize) ![]Count {
    const all = try gpa.alloc(Count, c.count());
    errdefer gpa.free(all);
    var it = c.iterator();
    var i: usize = 0;
    while (it.next()) |e| : (i += 1) all[i] = .{ .word = e.key_ptr.*, .n = e.value_ptr.* };
    std.mem.sort(Count, all, {}, moreCommon);
    const take = @min(k, all.len);
    const out = try gpa.dupe(Count, all[0..take]);
    gpa.free(all);
    return out;
}

test "cuenta palabras y most_common(2)" {
    const gpa = std.testing.allocator;
    var c = try countWords(gpa, "a b a c b a");
    defer c.deinit(gpa);
    try std.testing.expectEqual(@as(?usize, 3), c.get("a"));
    try std.testing.expectEqual(@as(?usize, 1), c.get("c"));
    const top = try mostCommon(gpa, &c, 2);
    defer gpa.free(top);
    try std.testing.expectEqual(@as(usize, 2), top.len);
    try std.testing.expectEqualStrings("a", top[0].word);
    try std.testing.expectEqual(@as(usize, 3), top[0].n);
    try std.testing.expectEqualStrings("b", top[1].word);
}

test "texto vacio: contador vacio y most_common vacio" {
    const gpa = std.testing.allocator;
    var c = try countWords(gpa, "  \n\t ");
    defer c.deinit(gpa);
    try std.testing.expectEqual(@as(u32, 0), c.count());
    const top = try mostCommon(gpa, &c, 5);
    defer gpa.free(top);
    try std.testing.expectEqual(@as(usize, 0), top.len);
}

test "k mayor que el numero de claves devuelve todas" {
    const gpa = std.testing.allocator;
    var c = try countWords(gpa, "x y");
    defer c.deinit(gpa);
    const top = try mostCommon(gpa, &c, 99);
    defer gpa.free(top);
    try std.testing.expectEqual(@as(usize, 2), top.len);
}

test "empates se desempatan alfabeticamente" {
    const gpa = std.testing.allocator;
    var c = try countWords(gpa, "pera manzana pera manzana kiwi");
    defer c.deinit(gpa);
    const top = try mostCommon(gpa, &c, 3);
    defer gpa.free(top);
    try std.testing.expectEqualStrings("manzana", top[0].word);
    try std.testing.expectEqualStrings("pera", top[1].word);
    try std.testing.expectEqualStrings("kiwi", top[2].word);
}

test "c[k] += n sobre clave ausente: getOrPut inicializa en 0" {
    const gpa = std.testing.allocator;
    var c: Counter = .empty;
    defer c.deinit(gpa);
    const gop = try c.getOrPut(gpa, "nuevo");
    try std.testing.expect(!gop.found_existing);
    gop.value_ptr.* = 0;
    gop.value_ptr.* += 5;
    try std.testing.expectEqual(@as(?usize, 5), c.get("nuevo"));
    // Counter de Python devuelve 0 para ausentes; aqui es null
    try std.testing.expect(c.get("ausente") == null);
}''',
    apis_used=['std.StringHashMapUnmanaged(usize)', 'HashMapUnmanaged.getOrPut', 'std.mem.tokenizeAny', 'std.mem.sort', 'HashMapUnmanaged.iterator', 'std.mem.Allocator.alloc', 'std.mem.Allocator.dupe'],
    constraints=['las claves de Counter son subslices del texto: el texto debe seguir vivo mientras exista el Counter', 'tokenizeAny sobre ASCII de espacio: split() de Python usa espacio Unicode'],
    preconditions=['text vive mas que el Counter'],
    postconditions=['mostCommon devuelve como maximo k entradas, en orden descendente de conteo', 'contar texto vacio da un Counter vacio'],
    side_effects=['asigna memoria para la tabla y para el resultado de mostCommon'],
    error_behavior='countWords/mostCommon: error.OutOfMemory (con errdefer, sin fugas).',
    ownership_memory='el Counter posee su tabla (deinit(gpa)); mostCommon devuelve un slice que el llamador libera con gpa.free.',
    differences=['Counter[ausente] devuelve 0 en Python; get() devuelve null', 'most_common desempata por orden de primera aparicion (dict ordenado); aqui los empates se ordenan alfabeticamente porque HashMap no conserva orden de insercion', 'str.split() separa en cualquier espacio Unicode; tokenizeAny con " \\t\\r\\n" solo separa esos ASCII', 'Counter admite conteos negativos y aritmetica (+,-); aqui usize', 'most_common(k) con k mayor que len devuelve todo; aqui tambien (@min)', 'most_common() sin k devuelve todo; pasar k = c.count()'],
    provenance=PROV),
]

CONTRACTS = {
    "zig0.16/dict-str-int-basic": _c(None, None, None, [],
        type_sig={"input": 'StringHashMap(i64) + claves []const u8', "output": '?i64 / bool / i64'},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/list-append-pop-insert": _c(None, None, None, [],
        type_sig={"input": 'ArrayList(i32) + gpa + indice isize', "output": '?i32 / i32 / void'},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/sorted-key-stable": _FUZZ["zig0.16/sorted-key-stable"],
    "zig0.16/set-str-membership": _c(None, None, None, [],
        type_sig={"input": 'StrSet + []const u8', "output": 'bool / usize'},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/heapq-priority-queue": _c(None, None, None, [],
        type_sig={"input": 'PriorityQueue(T) + comparador', "output": '?T'},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/deque-popleft-appendleft": _c(None, None, None, [],
        type_sig={"input": 'Deque(i32) + gpa', "output": '?i32 / void'},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/counter-most-common": _c(None, None, None, [],
        type_sig={"input": '[]const u8 texto + k: usize', "output": '[]Count'},
        skip_reason="sin driver diferencial todavia"),
}
