"""Recetas fs_rutas: rutas, listado, recorrido, creacion, temporales, copia y borrado.
Cada zig_test se verifico con `zig test` (Zig 0.16.0)."""
from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"; PY = "3.12"; PROV = "std local de zig 0.16.0 (repo en lib/std)"

ENTRIES = [
    dict(operation_id="zig0.16/path-join-basename-ext",
         name='unir y descomponer rutas (join, basename, dirname, splitext)',
         intent='Construir una ruta uniendo componentes y extraer directorio, nombre, stem y extension de una ruta, sin tocar el disco.',
         aliases=['os.path.join', 'os.path.basename', 'os.path.dirname', 'os.path.splitext', 'pathlib.Path.stem', 'pathlib.Path.suffix', 'unir rutas', 'nombre de archivo de una ruta', 'extension de archivo', 'directorio padre de una ruta', 'join paths', 'file extension', 'path components'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref='''import os
os.path.join("a", "b", "c.txt")          # 'a/b/c.txt'
os.path.basename("/data/logs/app.tar.gz") # 'app.tar.gz'
os.path.dirname("/data/logs/app.tar.gz")  # '/data/logs'
os.path.splitext("app.tar.gz")            # ('app.tar', '.gz')''',
         zig_impl='''pub fn joinPath(alloc: std.mem.Allocator, parts: []const []const u8) ![]u8 {
    return std.fs.path.join(alloc, parts);
}

pub const Split = struct {
    dir: []const u8,
    base: []const u8,
    stem: []const u8,
    ext: []const u8,
};

pub fn splitPath(p: []const u8) Split {
    return .{
        .dir = std.fs.path.dirname(p) orelse "",
        .base = std.fs.path.basename(p),
        .stem = std.fs.path.stem(p),
        .ext = std.fs.path.extension(p),
    };
}''',
         zig_test='''const std = @import("std");

pub fn joinPath(alloc: std.mem.Allocator, parts: []const []const u8) ![]u8 {
    return std.fs.path.join(alloc, parts);
}

pub const Split = struct {
    dir: []const u8,
    base: []const u8,
    stem: []const u8,
    ext: []const u8,
};

pub fn splitPath(p: []const u8) Split {
    return .{
        .dir = std.fs.path.dirname(p) orelse "",
        .base = std.fs.path.basename(p),
        .stem = std.fs.path.stem(p),
        .ext = std.fs.path.extension(p),
    };
}

test "join anade el separador y no duplica el existente" {
    const alloc = std.testing.allocator;
    const a = try joinPath(alloc, &.{ "a", "b", "c.txt" });
    defer alloc.free(a);
    try std.testing.expectEqualStrings("a/b/c.txt", a);
    const b = try joinPath(alloc, &.{ "a/", "b" });
    defer alloc.free(b);
    try std.testing.expectEqualStrings("a/b", b);
    const c = try joinPath(alloc, &.{ "", "x" });
    defer alloc.free(c);
    try std.testing.expectEqualStrings("x", c);
}

test "join NO reinicia con un componente absoluto (a diferencia de os.path.join)" {
    const alloc = std.testing.allocator;
    const a = try joinPath(alloc, &.{ "a", "/etc" });
    defer alloc.free(a);
    try std.testing.expectEqualStrings("a/etc", a);
}

test "basename dirname extension stem" {
    const s = splitPath("/data/logs/app.tar.gz");
    try std.testing.expectEqualStrings("/data/logs", s.dir);
    try std.testing.expectEqualStrings("app.tar.gz", s.base);
    try std.testing.expectEqualStrings("app.tar", s.stem);
    try std.testing.expectEqualStrings(".gz", s.ext);
}

test "bordes: sin directorio, dotfile, punto final, barra final" {
    const n = splitPath("main.zig");
    try std.testing.expectEqualStrings("", n.dir);
    try std.testing.expectEqualStrings(".zig", n.ext);
    // dotfile: sin extension (igual que splitext), pero stem de la ruta completa es una trampa
    try std.testing.expectEqualStrings("", splitPath("/x/.gitignore").ext);
    try std.testing.expectEqualStrings("/x/.gitignore", std.fs.path.stem("/x/.gitignore"));
    try std.testing.expectEqualStrings(".", splitPath("keep.").ext);
    // barra final: basename la ignora (Python devuelve "")
    try std.testing.expectEqualStrings("bam", std.fs.path.basename("/foo/bar/bam/"));
    // raiz: dirname null
    try std.testing.expect(std.fs.path.dirname("/") == null);
    try std.testing.expectEqualStrings("/", std.fs.path.dirname("/x").?);
}
''',
         apis_used=['std.fs.path.join', 'std.fs.path.basename', 'std.fs.path.dirname', 'std.fs.path.stem', 'std.fs.path.extension'],
         constraints=['sin root', 'no accede al disco'],
         preconditions=['componentes validos como bytes'],
         postconditions=['join devuelve memoria propia; basename/dirname/stem/extension son sub-slices de la entrada'],
         side_effects=[],
         error_behavior='join solo falla con OutOfMemory; dirname devuelve null si no hay directorio o es la raiz.',
         ownership_memory='join asigna: liberar con alloc.free. Las demas funciones no asignan y el resultado vive lo que viva la ruta de entrada.',
         differences=["os.path.join reinicia con un componente absoluto ('a','/etc' -> '/etc'); std.fs.path.join solo concatena ('a/etc'): usar std.fs.path.resolve si se quiere la semantica de Python", "dirname devuelve ?[]const u8: null (no '') sin directorio y tambien null para '/'; Python devuelve '' y '/' respectivamente", "basename ignora la barra final ('/a/b/' -> 'b'); Python devuelve ''", "stem(path) con un dotfile devuelve la RUTA COMPLETA ('/x/.gitignore'), no el nombre: trampa; splitext('.gitignore') da ('.gitignore','')", "extension incluye el punto y devuelve '' para dotfiles igual que splitext; 'keep.' da '.' en ambos", "std.fs.path usa el separador nativo (en Linux '/'); trabaja con bytes, sin normalizar unicode"],
         provenance=PROV),
    dict(operation_id="zig0.16/listdir-names-sorted",
         name='listar nombres de un directorio (listdir)',
         intent='Listar las entradas directas de un directorio con su nombre y tipo, devolviendo copias propias y orden determinista.',
         aliases=['os.listdir', 'os.scandir', 'pathlib.Path.iterdir', "Path.glob('*')", 'listar directorio', 'contenido de una carpeta', 'ls', 'list directory', 'iterate directory entries', 'DirEntry.is_dir', 'archivos de una carpeta', 'nombres de archivos'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref='''import os
sorted(os.listdir(path))                 # nombres, sin '.' ni '..'
for e in os.scandir(path):
    e.name, e.is_dir()''',
         zig_impl='''pub const Names = struct {
    arena: std.heap.ArenaAllocator,
    items: [][]const u8,

    pub fn deinit(self: *Names) void {
        self.arena.deinit();
    }
};

/// os.listdir(path) ordenado. `dir` debe abrirse con .iterate = true.
pub fn listDirSorted(io: std.Io, gpa: std.mem.Allocator, dir: std.Io.Dir) !Names {
    var arena = std.heap.ArenaAllocator.init(gpa);
    errdefer arena.deinit();
    var list: std.ArrayList([]const u8) = .empty;
    var it = dir.iterate();
    while (try it.next(io)) |entry| {
        try list.append(arena.allocator(), try arena.allocator().dupe(u8, entry.name));
    }
    const items = try list.toOwnedSlice(arena.allocator());
    std.mem.sort([]const u8, items, {}, struct {
        fn lt(_: void, a: []const u8, b: []const u8) bool {
            return std.mem.lessThan(u8, a, b);
        }
    }.lt);
    return .{ .arena = arena, .items = items };
}''',
         zig_test='''const std = @import("std");

pub const Names = struct {
    arena: std.heap.ArenaAllocator,
    items: [][]const u8,

    pub fn deinit(self: *Names) void {
        self.arena.deinit();
    }
};

/// os.listdir(path) ordenado. `dir` debe abrirse con .iterate = true.
pub fn listDirSorted(io: std.Io, gpa: std.mem.Allocator, dir: std.Io.Dir) !Names {
    var arena = std.heap.ArenaAllocator.init(gpa);
    errdefer arena.deinit();
    var list: std.ArrayList([]const u8) = .empty;
    var it = dir.iterate();
    while (try it.next(io)) |entry| {
        try list.append(arena.allocator(), try arena.allocator().dupe(u8, entry.name));
    }
    const items = try list.toOwnedSlice(arena.allocator());
    std.mem.sort([]const u8, items, {}, struct {
        fn lt(_: void, a: []const u8, b: []const u8) bool {
            return std.mem.lessThan(u8, a, b);
        }
    }.lt);
    return .{ .arena = arena, .items = items };
}

test "lista nombres de archivos y subdirectorios, sin . ni .." {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{ .iterate = true });
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "b.txt", .data = "1" });
    try tmp.dir.writeFile(io, .{ .sub_path = "a.txt", .data = "2" });
    try tmp.dir.createDir(io, "sub", .default_dir);
    var names = try listDirSorted(io, std.testing.allocator, tmp.dir);
    defer names.deinit();
    try std.testing.expectEqual(@as(usize, 3), names.items.len);
    try std.testing.expectEqualStrings("a.txt", names.items[0]);
    try std.testing.expectEqualStrings("b.txt", names.items[1]);
    try std.testing.expectEqualStrings("sub", names.items[2]);
}

test "directorio vacio da lista vacia" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{ .iterate = true });
    defer tmp.cleanup();
    var names = try listDirSorted(io, std.testing.allocator, tmp.dir);
    defer names.deinit();
    try std.testing.expectEqual(@as(usize, 0), names.items.len);
}

test "entry.kind distingue archivo de directorio (os.scandir is_dir)" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{ .iterate = true });
    defer tmp.cleanup();
    try tmp.dir.createDir(io, "d", .default_dir);
    var it = tmp.dir.iterate();
    const e = (try it.next(io)).?;
    try std.testing.expectEqual(std.Io.File.Kind.directory, e.kind);
    try std.testing.expect((try it.next(io)) == null);
}

test "directorio inexistente: error FileNotFound" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try std.testing.expectError(error.FileNotFound, tmp.dir.openDir(io, "no-existe", .{ .iterate = true }));
}
''',
         apis_used=['std.Io.Dir.iterate', 'std.Io.Dir.Iterator.next', 'std.Io.Dir.OpenOptions.iterate', 'std.Io.File.Kind', 'std.mem.sort', 'std.heap.ArenaAllocator'],
         constraints=['el Dir debe abrirse con .iterate = true', 'sin root'],
         preconditions=['directorio existente'],
         postconditions=["lista ordenada de nombres propios, sin '.' ni '..'"],
         side_effects=[],
         error_behavior='openDir falla con FileNotFound/NotDir/AccessDenied; it.next puede fallar con errores de E/S; nunca lanza excepciones.',
         ownership_memory='entry.name solo es valido hasta la siguiente llamada a next: hay que duplicar. Se usa una arena para liberar todo con deinit().',
         differences=['el orden de iterate es el del sistema de archivos (no definido); Python tambien, pero aqui se ordena explicitamente por bytes, no por locale', "iterate no devuelve '.' ni '..' (igual que listdir)", 'los nombres son bytes arbitrarios, no str: no hay decodificacion ni surrogateescape', 'iterar un Dir abierto sin .iterate = true es comportamiento ilegal (en Python no existe ese modo)', 'Entry.kind viene del dirent sin stat, como DirEntry.is_dir(); puede ser .unknown en algunos sistemas de archivos'],
         provenance=PROV),
    dict(operation_id="zig0.16/walk-tree-files",
         name='recorrer un arbol de directorios (os.walk)',
         intent='Recorrer recursivamente un directorio y recoger las rutas relativas de todos los archivos regulares.',
         aliases=['os.walk', 'os.scandir recursivo', 'pathlib.Path.rglob', "Path.rglob('*')", 'glob recursivo', 'recorrer carpetas recursivamente', 'buscar todos los archivos', 'walk directory tree', 'recursive file listing', 'find -type f', 'listar archivos de un arbol', 'topdown walk'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref='''import os
files = []
for root, dirs, names in os.walk(path):
    for n in names:
        files.append(os.path.relpath(os.path.join(root, n), path))
files.sort()''',
         zig_impl='''pub const Paths = struct {
    arena: std.heap.ArenaAllocator,
    items: [][]const u8,

    pub fn deinit(self: *Paths) void {
        self.arena.deinit();
    }
};

/// Rutas relativas (separador '/') de todos los ARCHIVOS regulares bajo `dir`,
/// ordenadas. `dir` debe abrirse con .iterate = true.
pub fn walkFiles(io: std.Io, gpa: std.mem.Allocator, dir: std.Io.Dir) !Paths {
    var arena = std.heap.ArenaAllocator.init(gpa);
    errdefer arena.deinit();
    var list: std.ArrayList([]const u8) = .empty;
    var walker = try dir.walk(gpa);
    defer walker.deinit();
    while (try walker.next(io)) |entry| {
        if (entry.kind != .file) continue;
        // entry.path solo vale hasta la siguiente llamada a next: copiar
        try list.append(arena.allocator(), try arena.allocator().dupe(u8, entry.path));
    }
    const items = try list.toOwnedSlice(arena.allocator());
    std.mem.sort([]const u8, items, {}, struct {
        fn lt(_: void, a: []const u8, b: []const u8) bool {
            return std.mem.lessThan(u8, a, b);
        }
    }.lt);
    return .{ .arena = arena, .items = items };
}''',
         zig_test='''const std = @import("std");

pub const Paths = struct {
    arena: std.heap.ArenaAllocator,
    items: [][]const u8,

    pub fn deinit(self: *Paths) void {
        self.arena.deinit();
    }
};

/// Rutas relativas (separador '/') de todos los ARCHIVOS regulares bajo `dir`,
/// ordenadas. `dir` debe abrirse con .iterate = true.
pub fn walkFiles(io: std.Io, gpa: std.mem.Allocator, dir: std.Io.Dir) !Paths {
    var arena = std.heap.ArenaAllocator.init(gpa);
    errdefer arena.deinit();
    var list: std.ArrayList([]const u8) = .empty;
    var walker = try dir.walk(gpa);
    defer walker.deinit();
    while (try walker.next(io)) |entry| {
        if (entry.kind != .file) continue;
        // entry.path solo vale hasta la siguiente llamada a next: copiar
        try list.append(arena.allocator(), try arena.allocator().dupe(u8, entry.path));
    }
    const items = try list.toOwnedSlice(arena.allocator());
    std.mem.sort([]const u8, items, {}, struct {
        fn lt(_: void, a: []const u8, b: []const u8) bool {
            return std.mem.lessThan(u8, a, b);
        }
    }.lt);
    return .{ .arena = arena, .items = items };
}

test "recorre recursivamente y devuelve rutas relativas de archivos" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{ .iterate = true });
    defer tmp.cleanup();
    try tmp.dir.createDirPath(io, "a/b");
    try tmp.dir.writeFile(io, .{ .sub_path = "top.txt", .data = "x" });
    try tmp.dir.writeFile(io, .{ .sub_path = "a/mid.txt", .data = "y" });
    try tmp.dir.writeFile(io, .{ .sub_path = "a/b/deep.txt", .data = "z" });
    var paths = try walkFiles(io, std.testing.allocator, tmp.dir);
    defer paths.deinit();
    try std.testing.expectEqual(@as(usize, 3), paths.items.len);
    try std.testing.expectEqualStrings("a/b/deep.txt", paths.items[0]);
    try std.testing.expectEqualStrings("a/mid.txt", paths.items[1]);
    try std.testing.expectEqualStrings("top.txt", paths.items[2]);
}

test "directorios vacios no aparecen como archivos; walker incluye directorios con kind" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{ .iterate = true });
    defer tmp.cleanup();
    try tmp.dir.createDirPath(io, "vacio/interior");
    var paths = try walkFiles(io, std.testing.allocator, tmp.dir);
    defer paths.deinit();
    try std.testing.expectEqual(@as(usize, 0), paths.items.len);

    var walker = try tmp.dir.walk(std.testing.allocator);
    defer walker.deinit();
    var dirs: usize = 0;
    while (try walker.next(io)) |e| {
        if (e.kind == .directory) dirs += 1;
    }
    try std.testing.expectEqual(@as(usize, 2), dirs);
}

test "depth cuenta niveles desde la raiz" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{ .iterate = true });
    defer tmp.cleanup();
    try tmp.dir.createDirPath(io, "a");
    try tmp.dir.writeFile(io, .{ .sub_path = "a/f", .data = "" });
    var walker = try tmp.dir.walk(std.testing.allocator);
    defer walker.deinit();
    var max_depth: usize = 0;
    while (try walker.next(io)) |e| max_depth = @max(max_depth, e.depth());
    try std.testing.expectEqual(@as(usize, 2), max_depth);
}
''',
         apis_used=['std.Io.Dir.walk', 'std.Io.Dir.Walker.next', 'std.Io.Dir.Walker.Entry', 'std.Io.Dir.Walker.deinit', 'std.Io.File.Kind', 'std.heap.ArenaAllocator'],
         constraints=['el Dir debe abrirse con .iterate = true', 'sin root'],
         preconditions=['directorio existente'],
         postconditions=["rutas relativas con '/' de todos los archivos, ordenadas"],
         side_effects=[],
         error_behavior='walker.next puede fallar (AccessDenied, etc.) y entonces se corta el recorrido; os.walk ignora errores por defecto.',
         ownership_memory='Walker asigna memoria (usar defer walker.deinit()); entry.path y entry.basename solo valen hasta el siguiente next: duplicar con una arena.',
         differences=['Walker.next devuelve archivos Y directorios en un unico flujo (con .kind); os.walk agrupa (root, dirs, files) por directorio', 'no hay topdown=False ni poda de os.walk modificando dirs; para podar usar walkSelectively', 'el orden es indefinido: aqui se ordena por bytes', 'los symlinks no se siguen como directorios (como followlinks=False); aparecen con kind .sym_link (verificado)', 'errores de permisos abortan el recorrido (os.walk los ignora sin onerror)', "las rutas usan el separador nativo '/' y son bytes, no str"],
         provenance=PROV),
    dict(operation_id="zig0.16/makedirs-exist-ok",
         name='crear directorios anidados (makedirs exist_ok)',
         intent='Crear un directorio y todos sus padres, sin error si ya existe, sabiendo si se creo algo.',
         aliases=['os.makedirs', 'os.makedirs exist_ok=True', 'os.mkdir', 'pathlib.Path.mkdir parents=True', 'mkdir -p', 'crear carpetas anidadas', 'crear directorio si no existe', 'create nested directories', 'ensure directory exists', 'createDirPath'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref='''import os
os.makedirs("a/b/c", exist_ok=True)
os.mkdir("a/b/c/d")   # no recursivo; FileExistsError si ya existe''',
         zig_impl='''/// os.makedirs(path, exist_ok=True): crea toda la cadena; devuelve true si creo algo.
pub fn makeDirs(io: std.Io, dir: std.Io.Dir, sub_path: []const u8) !bool {
    const status = try dir.createDirPathStatus(io, sub_path, .default_dir);
    return status == .created;
}''',
         zig_test='''const std = @import("std");

/// os.makedirs(path, exist_ok=True): crea toda la cadena; devuelve true si creo algo.
pub fn makeDirs(io: std.Io, dir: std.Io.Dir, sub_path: []const u8) !bool {
    const status = try dir.createDirPathStatus(io, sub_path, .default_dir);
    return status == .created;
}

test "crea la cadena completa y es idempotente (exist_ok=True)" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try std.testing.expect(try makeDirs(io, tmp.dir, "a/b/c"));
    try std.testing.expect(!try makeDirs(io, tmp.dir, "a/b/c"));
    var d = try tmp.dir.openDir(io, "a/b/c", .{});
    d.close(io);
}

test "createDirPath simple tambien es idempotente" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.createDirPath(io, "x/y");
    try tmp.dir.createDirPath(io, "x/y");
    try tmp.dir.createDirPath(io, "x");
}

test "createDir (os.mkdir) NO es recursivo y falla si existe" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try std.testing.expectError(error.FileNotFound, tmp.dir.createDir(io, "p/q", .default_dir));
    try tmp.dir.createDir(io, "p", .default_dir);
    try std.testing.expectError(error.PathAlreadyExists, tmp.dir.createDir(io, "p", .default_dir));
}

test "si en el camino hay un archivo regular, falla" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "f", .data = "x" });
    try std.testing.expectError(error.NotDir, tmp.dir.createDirPath(io, "f/sub"));
    try std.testing.expectError(error.NotDir, tmp.dir.createDirPath(io, "f"));
}
''',
         apis_used=['std.Io.Dir.createDirPath', 'std.Io.Dir.createDirPathStatus', 'std.Io.Dir.createDir', 'std.Io.Dir.CreatePathStatus'],
         constraints=['sin root', 'permisos de escritura en el padre'],
         preconditions=['Dir padre abierto'],
         postconditions=['toda la cadena de directorios existe'],
         side_effects=['crea directorios con permisos por defecto (default_dir)'],
         error_behavior='NotDir si un componente existente es un archivo; AccessDenied/ReadOnlyFileSystem/NoSpaceLeft segun el caso.',
         ownership_memory='sin asignacion de memoria.',
         differences=['createDirPath es siempre exist_ok=True: no existe el modo exist_ok=False; para eso usar createDir (os.mkdir), que falla con PathAlreadyExists', 'si la ruta final ya existe pero es un archivo, makedirs lanza FileExistsError y Zig devuelve NotDir', 'createDir no es recursivo: padre inexistente -> FileNotFound (igual que os.mkdir)', 'createDirPathStatus devuelve .existed/.created, algo que Python no informa', 'el modo por defecto es default_dir (observado 0o775 con umask 002), no 0o777 & ~umask explicito como en Python: pasar Permissions si importa'],
         provenance=PROV),
    dict(operation_id="zig0.16/temp-dir-scoped",
         name='directorio temporal con limpieza (TemporaryDirectory)',
         intent='Crear un directorio temporal con nombre aleatorio fuera de tests, usarlo y borrarlo con todo su contenido al terminar.',
         aliases=['tempfile.TemporaryDirectory', 'tempfile.mkdtemp', 'directorio temporal', 'carpeta temporal', 'temp dir cleanup', 'mkdtemp', 'scratch directory', 'with TemporaryDirectory()', 'testing.tmpDir fuera de tests', 'borrar al salir', 'se borra sola al terminar', 'limpieza automatica de temporales'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref='''import tempfile
with tempfile.TemporaryDirectory() as d:
    open(d + "/f.txt", "w").write("hola")
# al salir de with, d y su contenido ya no existen''',
         zig_impl='''/// Equivalente a tempfile.TemporaryDirectory fuera de tests: directorio con nombre
/// aleatorio dentro de `parent` (en produccion, openDirAbsolute("/tmp")).
/// `std.testing.tmpDir` solo compila en tests; esto funciona en cualquier binario.
pub const TempDir = struct {
    parent: std.Io.Dir,
    dir: std.Io.Dir,
    name: [name_len]u8,

    const random_bytes = 12;
    const name_len = std.base64.url_safe_no_pad.Encoder.calcSize(random_bytes) + 4;

    pub fn create(io: std.Io, parent: std.Io.Dir) !TempDir {
        var rnd: [random_bytes]u8 = undefined;
        io.random(&rnd);
        var name: [name_len]u8 = undefined;
        @memcpy(name[0..4], "tmp-");
        _ = std.base64.url_safe_no_pad.Encoder.encode(name[4..], &rnd);
        // createDir (no createDirPath): falla si ya existe, igual que mkdtemp
        try parent.createDir(io, &name, .default_dir);
        const dir = try parent.openDir(io, &name, .{ .iterate = true });
        return .{ .parent = parent, .dir = dir, .name = name };
    }

    /// Cierra y borra el arbol (como cleanup() / __exit__). Errores de borrado ignorados.
    pub fn cleanup(self: *TempDir, io: std.Io) void {
        self.dir.close(io);
        self.parent.deleteTree(io, &self.name) catch {};
    }
};''',
         zig_test='''const std = @import("std");

/// Equivalente a tempfile.TemporaryDirectory fuera de tests: directorio con nombre
/// aleatorio dentro de `parent` (en produccion, openDirAbsolute("/tmp")).
/// `std.testing.tmpDir` solo compila en tests; esto funciona en cualquier binario.
pub const TempDir = struct {
    parent: std.Io.Dir,
    dir: std.Io.Dir,
    name: [name_len]u8,

    const random_bytes = 12;
    const name_len = std.base64.url_safe_no_pad.Encoder.calcSize(random_bytes) + 4;

    pub fn create(io: std.Io, parent: std.Io.Dir) !TempDir {
        var rnd: [random_bytes]u8 = undefined;
        io.random(&rnd);
        var name: [name_len]u8 = undefined;
        @memcpy(name[0..4], "tmp-");
        _ = std.base64.url_safe_no_pad.Encoder.encode(name[4..], &rnd);
        // createDir (no createDirPath): falla si ya existe, igual que mkdtemp
        try parent.createDir(io, &name, .default_dir);
        const dir = try parent.openDir(io, &name, .{ .iterate = true });
        return .{ .parent = parent, .dir = dir, .name = name };
    }

    /// Cierra y borra el arbol (como cleanup() / __exit__). Errores de borrado ignorados.
    pub fn cleanup(self: *TempDir, io: std.Io) void {
        self.dir.close(io);
        self.parent.deleteTree(io, &self.name) catch {};
    }
};

test "crea un directorio vacio y usable; cleanup lo elimina" {
    const io = std.testing.io;
    var base = std.testing.tmpDir(.{});
    defer base.cleanup();
    var t = try TempDir.create(io, base.dir);
    try t.dir.writeFile(io, .{ .sub_path = "f.txt", .data = "hola" });
    const got = try t.dir.readFileAlloc(io, "f.txt", std.testing.allocator, .limited(16));
    defer std.testing.allocator.free(got);
    try std.testing.expectEqualStrings("hola", got);
    const saved = t.name;
    t.cleanup(io);
    try std.testing.expectError(error.FileNotFound, base.dir.openDir(io, &saved, .{}));
}

test "cleanup borra tambien el contenido anidado" {
    const io = std.testing.io;
    var base = std.testing.tmpDir(.{});
    defer base.cleanup();
    var t = try TempDir.create(io, base.dir);
    try t.dir.createDirPath(io, "a/b");
    try t.dir.writeFile(io, .{ .sub_path = "a/b/x", .data = "1" });
    const saved = t.name;
    t.cleanup(io);
    try std.testing.expectError(error.FileNotFound, base.dir.statFile(io, &saved, .{}));
}

test "dos directorios temporales tienen nombres distintos" {
    const io = std.testing.io;
    var base = std.testing.tmpDir(.{});
    defer base.cleanup();
    var a = try TempDir.create(io, base.dir);
    defer a.cleanup(io);
    var b = try TempDir.create(io, base.dir);
    defer b.cleanup(io);
    try std.testing.expect(!std.mem.eql(u8, &a.name, &b.name));
}
''',
         apis_used=['std.Io.random', 'std.base64.url_safe_no_pad.Encoder', 'std.Io.Dir.createDir', 'std.Io.Dir.openDir', 'std.Io.Dir.deleteTree', 'std.Io.Dir.openDirAbsolute'],
         constraints=['sin root', 'padre escribible (p. ej. /tmp via Dir.openDirAbsolute)'],
         preconditions=['Dir padre abierto'],
         postconditions=['directorio nuevo, vacio, con nombre unico; cleanup elimina el arbol'],
         side_effects=['crea y borra un directorio'],
         error_behavior='createDir falla con PathAlreadyExists en colision (probabilidad despreciable con 96 bits); cleanup ignora errores de borrado.',
         ownership_memory='TempDir no asigna memoria (nombre en array fijo). Llamar cleanup(io) con defer; no usar el Dir despues.',
         differences=['std.testing.tmpDir solo compila en tests (asserts builtin.is_test) y vive en .zig-cache/tmp; no sirve en binarios normales', 'no hay __exit__/with: el limpiado es manual con defer; si el proceso muere (SIGKILL) el directorio queda', 'TemporaryDirectory elige el padre con TMPDIR/tempdir; aqui el padre es explicito y no se leen variables de entorno', 'mkdtemp crea con permisos 0o700; aqui se usa default_dir (observado 0o775, sujeto a umask): pasar Permissions si se requiere privacidad', "el nombre es 'tmp-' + base64url, no el prefijo 'tmp' + [a-z0-9_] de Python"],
         provenance=PROV),
    dict(operation_id="zig0.16/copyfile-replace",
         name='copiar un archivo (shutil.copyfile)',
         intent='Copiar el contenido de un archivo a otro destino, sobrescribiendo o negandose a pisar uno existente.',
         aliases=['shutil.copyfile', 'shutil.copy', 'shutil.copy2', 'copiar archivo', 'copy file', 'duplicar un archivo', 'cp', 'Dir.copyFile', 'copiar sin sobrescribir', 'copy no clobber', 'copiar fichero atomicamente'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref='''import shutil
shutil.copyfile("a.txt", "b.txt")    # sobrescribe b.txt si existe
with open("a.txt", "rb") as s, open("c.txt", "xb") as d:   # sin pisar: FileExistsError
    shutil.copyfileobj(s, d)''',
         zig_impl='''/// shutil.copyfile(src, dst): copia el contenido de un archivo; sobrescribe dst.
pub fn copyFile(io: std.Io, dir: std.Io.Dir, src: []const u8, dst: []const u8) !void {
    try dir.copyFile(src, dir, dst, io, .{});
}

/// Variante que se niega a pisar un destino existente (como open(dst, "x")).
pub fn copyFileNoClobber(io: std.Io, dir: std.Io.Dir, src: []const u8, dst: []const u8) !void {
    try dir.copyFile(src, dir, dst, io, .{ .replace = false });
}''',
         zig_test='''const std = @import("std");

/// shutil.copyfile(src, dst): copia el contenido de un archivo; sobrescribe dst.
pub fn copyFile(io: std.Io, dir: std.Io.Dir, src: []const u8, dst: []const u8) !void {
    try dir.copyFile(src, dir, dst, io, .{});
}

/// Variante que se niega a pisar un destino existente (como open(dst, "x")).
pub fn copyFileNoClobber(io: std.Io, dir: std.Io.Dir, src: []const u8, dst: []const u8) !void {
    try dir.copyFile(src, dir, dst, io, .{ .replace = false });
}

test "copia el contenido y deja el original intacto" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "a.txt", .data = "contenido\\n" });
    try copyFile(io, tmp.dir, "a.txt", "b.txt");
    const got = try tmp.dir.readFileAlloc(io, "b.txt", alloc, .limited(64));
    defer alloc.free(got);
    try std.testing.expectEqualStrings("contenido\\n", got);
    const orig = try tmp.dir.readFileAlloc(io, "a.txt", alloc, .limited(64));
    defer alloc.free(orig);
    try std.testing.expectEqualStrings("contenido\\n", orig);
}

test "por defecto sobrescribe un destino existente (mas largo)" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "src", .data = "corto" });
    try tmp.dir.writeFile(io, .{ .sub_path = "dst", .data = "destino-muy-largo" });
    try copyFile(io, tmp.dir, "src", "dst");
    const got = try tmp.dir.readFileAlloc(io, "dst", alloc, .limited(64));
    defer alloc.free(got);
    try std.testing.expectEqualStrings("corto", got);
}

test "no-clobber falla con PathAlreadyExists y no toca el destino" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "src", .data = "nuevo" });
    try tmp.dir.writeFile(io, .{ .sub_path = "dst", .data = "previo" });
    try std.testing.expectError(error.PathAlreadyExists, copyFileNoClobber(io, tmp.dir, "src", "dst"));
    const got = try tmp.dir.readFileAlloc(io, "dst", alloc, .limited(64));
    defer alloc.free(got);
    try std.testing.expectEqualStrings("previo", got);
}

test "origen inexistente: FileNotFound; destino en directorio inexistente tambien" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try std.testing.expectError(error.FileNotFound, copyFile(io, tmp.dir, "no-existe", "x"));
    try tmp.dir.writeFile(io, .{ .sub_path = "src", .data = "1" });
    try std.testing.expectError(error.FileNotFound, copyFile(io, tmp.dir, "src", "falta/dst"));
}

test "archivo vacio y copia de bytes binarios" {
    const alloc = std.testing.allocator;
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "e", .data = "" });
    try copyFile(io, tmp.dir, "e", "e2");
    const st = try tmp.dir.statFile(io, "e2", .{});
    try std.testing.expectEqual(@as(u64, 0), st.size);
    try tmp.dir.writeFile(io, .{ .sub_path = "bin", .data = &[_]u8{ 0, 255, 10, 13, 0 } });
    try copyFile(io, tmp.dir, "bin", "bin2");
    const got = try tmp.dir.readFileAlloc(io, "bin2", alloc, .limited(16));
    defer alloc.free(got);
    try std.testing.expectEqualSlices(u8, &[_]u8{ 0, 255, 10, 13, 0 }, got);
}
''',
         apis_used=['std.Io.Dir.copyFile', 'std.Io.Dir.CopyFileOptions', 'std.Io.Dir.createFileAtomic'],
         constraints=['sin root', 'origen y destino bajo Dirs abiertos'],
         preconditions=['origen existente y legible'],
         postconditions=['destino tiene los mismos bytes que el origen; el origen no cambia'],
         side_effects=['crea/reemplaza el archivo destino'],
         error_behavior='FileNotFound si falta el origen o el directorio del destino; PathAlreadyExists con replace = false; errores de E/S.',
         ownership_memory='sin asignacion de memoria (buffer de 1 KiB en pila); la copia es atomica via archivo temporal + rename/link.',
         differences=['copyFile copia por defecto los PERMISOS del origen (options.permissions = null); shutil.copyfile NO copia permisos (usa umask): pasar .permissions explicitos para igualar', 'la escritura es atomica (temporal en el directorio destino y rename): un fallo no deja un destino a medias; Python escribe in situ', "replace = false da PathAlreadyExists; Python no tiene esa opcion en copyfile (hay que usar open(dst,'x'))", 'copiar un archivo sobre si mismo no lanza SameFileError (Python si); el contenido queda intacto', 'make_path = true crea los directorios del destino; Python falla con FileNotFoundError', 'no copia metadatos (mtime, xattrs) ni sigue la semantica de copy2'],
         provenance=PROV),
    dict(operation_id="zig0.16/remove-file-rmtree",
         name='borrar archivo, directorio vacio o arbol (remove, rmdir, rmtree)',
         intent='Eliminar un archivo, un directorio vacio o un arbol completo de forma explicita.',
         aliases=['os.remove', 'os.unlink', 'os.rmdir', 'shutil.rmtree', 'borrar archivo', 'eliminar carpeta recursivamente', 'rm -rf', 'delete directory tree', 'deleteFile', 'deleteTree', 'deleteDir', 'remove file', 'borrar directorio'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref='''import os, shutil
os.remove("f")            # FileNotFoundError / IsADirectoryError
os.rmdir("d")             # OSError si no esta vacio
shutil.rmtree("t")        # FileNotFoundError si no existe''',
         zig_impl='''/// os.remove(path): borra un archivo (o symlink). Falla si no existe o es directorio.
pub fn removeFile(io: std.Io, dir: std.Io.Dir, sub_path: []const u8) !void {
    try dir.deleteFile(io, sub_path);
}

/// os.rmdir(path): solo directorios vacios.
pub fn removeEmptyDir(io: std.Io, dir: std.Io.Dir, sub_path: []const u8) !void {
    try dir.deleteDir(io, sub_path);
}

/// shutil.rmtree(path): borra el arbol entero. NO falla si no existe (rmtree sin
/// ignore_errors lanza FileNotFoundError). Para exigir el error, comprobar antes con statFile.
pub fn removeTree(io: std.Io, dir: std.Io.Dir, sub_path: []const u8) !void {
    try dir.deleteTree(io, sub_path);
}''',
         zig_test='''const std = @import("std");

/// os.remove(path): borra un archivo (o symlink). Falla si no existe o es directorio.
pub fn removeFile(io: std.Io, dir: std.Io.Dir, sub_path: []const u8) !void {
    try dir.deleteFile(io, sub_path);
}

/// os.rmdir(path): solo directorios vacios.
pub fn removeEmptyDir(io: std.Io, dir: std.Io.Dir, sub_path: []const u8) !void {
    try dir.deleteDir(io, sub_path);
}

/// shutil.rmtree(path): borra el arbol entero. NO falla si no existe (rmtree sin
/// ignore_errors lanza FileNotFoundError). Para exigir el error, comprobar antes con statFile.
pub fn removeTree(io: std.Io, dir: std.Io.Dir, sub_path: []const u8) !void {
    try dir.deleteTree(io, sub_path);
}

test "removeFile borra y luego falla con FileNotFound" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "f", .data = "x" });
    try removeFile(io, tmp.dir, "f");
    try std.testing.expectError(error.FileNotFound, tmp.dir.statFile(io, "f", .{}));
    try std.testing.expectError(error.FileNotFound, removeFile(io, tmp.dir, "f"));
}

test "removeFile sobre un directorio falla con IsDir" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.createDir(io, "d", .default_dir);
    try std.testing.expectError(error.IsDir, removeFile(io, tmp.dir, "d"));
}

test "removeEmptyDir: vacio ok, con contenido DirNotEmpty" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.createDirPath(io, "d/e");
    try std.testing.expectError(error.DirNotEmpty, removeEmptyDir(io, tmp.dir, "d"));
    try removeEmptyDir(io, tmp.dir, "d/e");
    try removeEmptyDir(io, tmp.dir, "d");
}

test "removeTree borra un arbol con archivos y subdirectorios" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.createDirPath(io, "t/a/b");
    try tmp.dir.writeFile(io, .{ .sub_path = "t/x", .data = "1" });
    try tmp.dir.writeFile(io, .{ .sub_path = "t/a/b/y", .data = "2" });
    try removeTree(io, tmp.dir, "t");
    try std.testing.expectError(error.FileNotFound, tmp.dir.statFile(io, "t", .{}));
}

test "removeTree de una ruta inexistente NO es error (a diferencia de rmtree)" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try removeTree(io, tmp.dir, "no-existe");
}

test "removeTree tambien borra un archivo suelto" {
    const io = std.testing.io;
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(io, .{ .sub_path = "solo", .data = "1" });
    try removeTree(io, tmp.dir, "solo");
    try std.testing.expectError(error.FileNotFound, tmp.dir.statFile(io, "solo", .{}));
}
''',
         apis_used=['std.Io.Dir.deleteFile', 'std.Io.Dir.deleteDir', 'std.Io.Dir.deleteTree'],
         constraints=['sin root', 'DESTRUCTIVO: usar solo sobre rutas propias (en tests, un tmpDir)'],
         preconditions=['Dir padre abierto'],
         postconditions=['la ruta ya no existe'],
         side_effects=['borra archivos y directorios'],
         error_behavior='deleteFile: FileNotFound, IsDir; deleteDir: DirNotEmpty, FileNotFound; deleteTree: no falla si no existe.',
         ownership_memory='sin asignacion de memoria visible; deleteTree usa una pila interna acotada.',
         differences=['deleteTree sobre una ruta inexistente NO es error; shutil.rmtree lanza FileNotFoundError: comprobar antes con statFile si se quiere ese error', 'deleteTree tambien borra un archivo suelto o un symlink (rmtree lanza NotADirectoryError sobre un archivo)', "deleteTree borra symlinks como enlaces (la doc de std: 'file, directory o symlink'); no verificado con destino directorio", 'deleteFile sobre un directorio da IsDir (Python: IsADirectoryError en Linux)', 'deleteDir con contenido da DirNotEmpty (Python: OSError errno ENOTEMPTY)', 'operaciones irreversibles y no atomicas: un error a mitad deja el arbol parcialmente borrado'],
         provenance=PROV),
]

CONTRACTS = {
    "zig0.16/path-join-basename-ext": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/listdir-names-sorted": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/walk-tree-files": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/makedirs-exist-ok": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/temp-dir-scoped": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/copyfile-replace": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/remove-file-rmtree": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
}
