"""Recetas io_red: hilos, sincronizacion, std.Io (async/Group), sockets TCP/UDP, cliente HTTP y FFI.
Cada zig_test se verifico con `zig test` (Zig 0.16.0). Todo es hermetico: solo loopback 127.0.0.1, puerto 0."""
from pyzig.fuzz.contracts import _c

ZIG = "0.16.0"; PY = "3.12"; PROV = "std local de zig 0.16.0 (repo en lib/std): Thread.zig, Io.zig, Io/net.zig, http/Client.zig, http/Server.zig"

ENTRIES = [
    dict(operation_id='zig0.16/thread-spawn-join',
         name='lanzar hilos y esperarlos (threading.Thread + join)',
         intent='Ejecutar una funcion en uno o varios hilos del SO, esperar a que terminen y recoger su resultado sin carreras.',
         aliases=['threading.Thread', 'Thread.start', 'Thread.join', 'threading.Thread(target=f, args=...)', 'lanzar un hilo', 'crear hilos y esperar', 'esperar a que termine un hilo', 'spawn thread', 'join thread', 'worker threads', 'paralelismo con hilos'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref=r'''import threading
res = [0] * 4
def work(k):
    res[k] = sum(range(k * 10, k * 10 + 10))
ts = [threading.Thread(target=work, args=(k,)) for k in range(4)]
for t in ts: t.start()
for t in ts: t.join()''',
         zig_impl=r'''fn sumRange(lo: u64, hi: u64, out: *u64) void {
    var s: u64 = 0;
    var i = lo;
    while (i < hi) : (i += 1) s += i;
    out.* = s;
}''',
         zig_test=r'''const std = @import("std");

fn sumRange(lo: u64, hi: u64, out: *u64) void {
    var s: u64 = 0;
    var i = lo;
    while (i < hi) : (i += 1) s += i;
    out.* = s;
}

test "spawn + join con resultado por puntero" {
    var r: u64 = 0;
    const t = try std.Thread.spawn(.{}, sumRange, .{ 0, 101, &r });
    t.join();
    try std.testing.expectEqual(@as(u64, 5050), r);
}

test "varios hilos, cada uno escribe su propio slot" {
    var res = [_]u64{0} ** 4;
    var ths: [4]std.Thread = undefined;
    for (&ths, 0..) |*t, k| {
        t.* = try std.Thread.spawn(.{}, sumRange, .{ k * 10, k * 10 + 10, &res[k] });
    }
    for (ths) |t| t.join();
    try std.testing.expectEqual(@as(u64, 45), res[0]);
    try std.testing.expectEqual(@as(u64, 145), res[1]);
    try std.testing.expectEqual(@as(u64, 245), res[2]);
    try std.testing.expectEqual(@as(u64, 345), res[3]);
}
''',
         apis_used=['std.Thread.spawn', 'std.Thread.join', 'std.Thread.detach'],
         constraints=['sin root', 'sin red', 'requiere soporte de hilos (no wasm single-threaded)'],
         preconditions=['la funcion del hilo no devuelve error (su retorno debe ser void o un entero)'],
         postconditions=['tras join() el hilo termino y sus escrituras son visibles para el llamador'],
         side_effects=['crea hilos del SO'],
         error_behavior='spawn devuelve error (SpawnError: ThreadQuotaExceeded, SystemResources, OutOfMemory, LockedMemoryLimitExceeded, Unexpected); join no falla.',
         ownership_memory='Los argumentos se copian al hilo por valor en la tupla; un puntero a una variable local es valido solo si se hace join antes de que esa variable salga de ambito. No hay GIL ni valor de retorno: el resultado se devuelve escribiendo por puntero.',
         differences=['Thread.join() de Python no devuelve valor; Thread.join de Zig tampoco: el resultado se pasa por un puntero (*u64) o una estructura compartida, y hay que hacer join antes de leerlo', "start() de Python es aparte del constructor; std.Thread.spawn crea Y arranca el hilo a la vez, no hay estado 'creado sin iniciar'", 'Cada hilo debe terminar con join() o detach(), nunca ambos ni ninguno: olvidar ambos filtra el hilo (Python hace join implicito al salir salvo daemon)', 'Si la funcion del hilo devuelve un error no manejado, no se propaga a quien hace join (en Zig 0.16 el tipo de retorno permitido es void/entero/noreturn): captura el error dentro del hilo y guardalo por puntero', 'Ownership de datos: pasar &variable_local es seguro solo si join ocurre antes de que la variable muera; con detach() no hay forma segura de pasar locales', 'Sin GIL: dos hilos escribiendo la misma variable es una carrera de datos real (UB); usar atomics o Io.Mutex, o slots disjuntos como aqui', 'std.Thread.Mutex/Condition/WaitGroup NO existen en 0.16 (ahora estan en std.Io)'],
         provenance=PROV),
    dict(operation_id='zig0.16/thread-shared-counter',
         name='contador compartido entre hilos (threading.Lock / atomics)',
         intent='Incrementar un contador desde varios hilos sin perder actualizaciones, con atomics o con un mutex de std.Io.',
         aliases=['threading.Lock', 'with lock:', 'Lock.acquire', 'Lock.release', 'contador compartido entre hilos', 'race condition', 'exclusion mutua', 'mutex', 'atomic counter', 'std.atomic.Value', 'proteger variable compartida', 'itertools.count thread-safe'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref=r'''import threading
n = 0
lock = threading.Lock()
def inc():
    global n
    for _ in range(1000):
        with lock:
            n += 1
ts = [threading.Thread(target=inc) for _ in range(4)]
for t in ts: t.start()
for t in ts: t.join()
assert n == 4000''',
         zig_impl=r'''const Shared = struct {
    m: std.Io.Mutex = .init,
    n: u32 = 0,

    fn run(s: *Shared, io: std.Io) void {
        for (0..1000) |_| {
            s.m.lockUncancelable(io);
            defer s.m.unlock(io);
            s.n += 1;
        }
    }
};

fn incAtomic(c: *std.atomic.Value(u32)) void {
    for (0..1000) |_| _ = c.fetchAdd(1, .monotonic);
}''',
         zig_test=r'''const std = @import("std");

const Shared = struct {
    m: std.Io.Mutex = .init,
    n: u32 = 0,

    fn run(s: *Shared, io: std.Io) void {
        for (0..1000) |_| {
            s.m.lockUncancelable(io);
            defer s.m.unlock(io);
            s.n += 1;
        }
    }
};

fn incAtomic(c: *std.atomic.Value(u32)) void {
    for (0..1000) |_| _ = c.fetchAdd(1, .monotonic);
}

test "contador compartido: atomics" {
    var counter = std.atomic.Value(u32).init(0);
    var ths: [4]std.Thread = undefined;
    for (&ths) |*t| t.* = try std.Thread.spawn(.{}, incAtomic, .{&counter});
    for (ths) |t| t.join();
    try std.testing.expectEqual(@as(u32, 4000), counter.load(.monotonic));
}

test "contador compartido: std.Io.Mutex (necesita un Io)" {
    var threaded: std.Io.Threaded = .init(std.testing.allocator, .{});
    defer threaded.deinit();
    const io = threaded.io();
    var sh: Shared = .{};
    var ths: [4]std.Thread = undefined;
    for (&ths) |*t| t.* = try std.Thread.spawn(.{}, Shared.run, .{ &sh, io });
    for (ths) |t| t.join();
    try std.testing.expectEqual(@as(u32, 4000), sh.n);
}

test "tryLock: no bloquea si ya esta tomado" {
    var m: std.Io.Mutex = .init;
    try std.testing.expect(m.tryLock());
    try std.testing.expect(!m.tryLock());
}
''',
         apis_used=['std.atomic.Value', 'std.atomic.Value.fetchAdd', 'std.Io.Mutex', 'std.Io.Mutex.lockUncancelable', 'std.Io.Mutex.unlock', 'std.Io.Mutex.tryLock', 'std.Io.Threaded'],
         constraints=['sin root', 'sin red'],
         preconditions=['el Mutex no se mueve ni se copia mientras haya hilos que lo usen'],
         postconditions=['las 4000 actualizaciones se ven al hacer join'],
         side_effects=['crea hilos del SO'],
         error_behavior='Io.Mutex.lock devuelve error.Canceled (punto de cancelacion); lockUncancelable no falla. atomics no fallan.',
         ownership_memory='El Mutex vive en el llamador y se comparte por puntero; no hay with-bloque: el desbloqueo se hace con defer m.unlock(io) justo despues de lock. Un std.Io.Threaded debe sobrevivir a todos los hilos que usan su Io.',
         differences=["No hay 'with lock:': hay que emparejar a mano lock con 'defer unlock'; olvidar unlock bloquea para siempre", 'std.Io.Mutex.lock/unlock reciben un Io (es el que sabe dormir/despertar al hilo); el Mutex solo no basta. std.Thread.Mutex ya no existe en 0.16', 'tryLock() no recibe Io y devuelve bool (equivale a lock.acquire(blocking=False))', 'lock() puede devolver error.Canceled; lockUncancelable() es el equivalente al acquire() de Python que nunca falla', 'El Mutex no es reentrante (igual que threading.Lock, no RLock): tomarlo dos veces en el mismo hilo es un bloqueo mortal', 'Para un contador simple, std.atomic.Value(u32).fetchAdd es mas barato que un mutex y no necesita Io; hay que elegir el std.builtin.AtomicOrder (.monotonic basta para un contador, .acquire/.release para publicar datos)', "Sin GIL: 'n += 1' sobre un u32 compartido sin atomics ni mutex es una carrera de datos (UB), no solo resultados raros"],
         provenance=PROV),
    dict(operation_id='zig0.16/io-async-group-future',
         name='concurrencia con std.Io: async/await, concurrent y Group',
         intent='Lanzar tareas con std.Io (Future con await, concurrent garantizada, Group para esperar un conjunto), equivalente a asyncio.gather o ThreadPoolExecutor.',
         aliases=['asyncio.gather', 'asyncio.create_task', 'asyncio.run', 'await', 'ThreadPoolExecutor.submit', 'concurrent.futures', 'Future.result', 'asyncio.TaskGroup', 'tareas concurrentes', 'async await', 'Io.async', 'Io.Group', 'executor de hilos'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref=r'''import asyncio
async def square(x): return x * x
async def main():
    a, b = await asyncio.gather(square(6), square(7))
    return a, b
asyncio.run(main())   # (36, 49)''',
         zig_impl=r'''fn square(x: u32) u32 {
    return x * x;
}

fn addTo(total: *std.atomic.Value(u32), n: u32) void {
    _ = total.fetchAdd(n, .monotonic);
}''',
         zig_test=r'''const std = @import("std");

fn square(x: u32) u32 {
    return x * x;
}

fn addTo(total: *std.atomic.Value(u32), n: u32) void {
    _ = total.fetchAdd(n, .monotonic);
}

test "Io.async + await (Future)" {
    var threaded: std.Io.Threaded = .init(std.testing.allocator, .{});
    defer threaded.deinit();
    const io = threaded.io();
    var f1 = io.async(square, .{6});
    var f2 = io.async(square, .{7});
    try std.testing.expectEqual(@as(u32, 36), f1.await(io));
    try std.testing.expectEqual(@as(u32, 49), f2.await(io));
}

test "Io.concurrent: concurrencia garantizada (puede fallar con ConcurrencyUnavailable)" {
    var threaded: std.Io.Threaded = .init(std.testing.allocator, .{});
    defer threaded.deinit();
    const io = threaded.io();
    var f = try io.concurrent(square, .{9});
    try std.testing.expectEqual(@as(u32, 81), f.await(io));
}

test "Io.Group: await de todas las tareas" {
    var threaded: std.Io.Threaded = .init(std.testing.allocator, .{});
    defer threaded.deinit();
    const io = threaded.io();
    var total = std.atomic.Value(u32).init(0);
    var g: std.Io.Group = .init;
    for (1..11) |k| g.async(io, addTo, .{ &total, @as(u32, @intCast(k)) });
    try g.await(io);
    try std.testing.expectEqual(@as(u32, 55), total.load(.monotonic));
}

test "Io.Threaded.init_single_threaded: concurrent no esta disponible, async corre inline" {
    var threaded: std.Io.Threaded = .init_single_threaded;
    const io = threaded.io();
    try std.testing.expectError(error.ConcurrencyUnavailable, io.concurrent(square, .{2}));
    var f = io.async(square, .{5});
    try std.testing.expectEqual(@as(u32, 25), f.await(io));
}
''',
         apis_used=['std.Io.Threaded', 'std.Io.async', 'std.Io.concurrent', 'std.Io.Future.await', 'std.Io.Group', 'std.Io.Group.async', 'std.Io.Group.await'],
         constraints=['sin root', 'sin red'],
         preconditions=['un std.Io.Threaded inicializado y vivo mientras haya tareas'],
         postconditions=['await devuelve el valor de retorno de la funcion; Group.await vuelve cuando todas las tareas terminaron'],
         side_effects=['puede crear hilos de un pool interno'],
         error_behavior='io.concurrent devuelve error.ConcurrencyUnavailable si el Io no admite concurrencia real o hay agotamiento de recursos; Group.await devuelve error.Canceled si se cancela; Future.await no falla (el resultado es el retorno de la funcion).',
         ownership_memory='Los args se copian en el momento de la llamada; punteros a locales son validos solo hasta el await/cancel. Todo Future debe terminar con await o cancel y todo Group con Group.await o Group.cancel, o se filtran recursos. io.async puede ejecutar la funcion inmediatamente, antes de volver.',
         differences=["No hay palabras clave async/await en el lenguaje: son llamadas a io.async(fn, .{args}) y future.await(io); las funciones son normales (sin 'colorear')", 'io.async NO garantiza concurrencia (puede correr inline y completar antes de volver); si el programa necesita concurrencia real, p.ej. un servidor y su cliente que se esperan entre si, usa io.concurrent, que puede fallar con ConcurrencyUnavailable (con init_single_threaded siempre falla)', "Un Future siempre debe consumirse con await() o cancel(); soltarlo filtra la tarea (Python solo avisa 'Task was destroyed')", 'Group.async: la funcion debe devolver void o Cancelable!void, no hay valores de retorno por tarea (a diferencia de gather): comunica resultados por punteros o atomics', 'Los hilos compartiendo datos siguen necesitando atomics o Io.Mutex: io.async con threads reales tiene carreras de datos como cualquier hilo', 'asyncio es cooperativo en un solo hilo; std.Io.Threaded usa hilos del SO reales: el codigo bloqueante dentro de una tarea no congela el resto', 'Io.Threaded necesita un allocator thread-safe (aqui std.testing.allocator); con Allocator.failing solo sirven las operaciones que no lancen tareas'],
         provenance=PROV),
    dict(operation_id='zig0.16/tcp-loopback-echo',
         name='servidor y cliente TCP en 127.0.0.1 (socket listen/accept/connect)',
         intent='Abrir un servidor TCP en loopback con puerto efimero, conectar un cliente, enviar una linea y recibir el eco, todo en el mismo proceso.',
         aliases=['socket.socket', 'socket.bind', 'socket.listen', 'socket.accept', 'socket.connect', 'socketserver.TCPServer', 'asyncio.start_server', 'servidor TCP', 'cliente TCP', 'eco TCP', 'sockets en loopback', 'puerto 0', 'getsockname'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref=r'''import socket, threading
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
port = srv.getsockname()[1]
def serve():
    c, _ = srv.accept()
    c.sendall(b"eco:" + c.makefile().readline().encode())
threading.Thread(target=serve).start()
cli = socket.create_connection(("127.0.0.1", port))
cli.sendall(b"hola\n"); print(cli.makefile().readline())''',
         zig_impl=r'''const net = std.Io.net;

fn echoOnce(io: std.Io, server: *net.Server) !void {
    const conn = try server.accept(io);
    defer conn.close(io);
    var rbuf: [64]u8 = undefined;
    var wbuf: [64]u8 = undefined;
    var r = conn.reader(io, &rbuf);
    var w = conn.writer(io, &wbuf);
    const line = try r.interface.takeDelimiterExclusive('\n');
    try w.interface.writeAll("eco:");
    try w.interface.writeAll(line);
    try w.interface.writeAll("\n");
    try w.interface.flush();
}''',
         zig_test=r'''const std = @import("std");

const net = std.Io.net;

fn echoOnce(io: std.Io, server: *net.Server) !void {
    const conn = try server.accept(io);
    defer conn.close(io);
    var rbuf: [64]u8 = undefined;
    var wbuf: [64]u8 = undefined;
    var r = conn.reader(io, &rbuf);
    var w = conn.writer(io, &wbuf);
    const line = try r.interface.takeDelimiterExclusive('\n');
    try w.interface.writeAll("eco:");
    try w.interface.writeAll(line);
    try w.interface.writeAll("\n");
    try w.interface.flush();
}

test "TCP loopback puerto 0: servidor y cliente en el mismo test" {
    var threaded: std.Io.Threaded = .init(std.testing.allocator, .{});
    defer threaded.deinit();
    const io = threaded.io();

    const any = net.IpAddress{ .ip4 = net.Ip4Address.loopback(0) };
    var server = try any.listen(io, .{ .reuse_address = true });
    defer server.deinit(io);
    const port = server.socket.address.getPort();
    try std.testing.expect(port != 0);

    // el servidor corre en otra tarea: accept bloquea, y el cliente de este mismo hilo tiene que conectar
    var srv = try io.concurrent(echoOnce, .{ io, &server });

    const dest = net.IpAddress{ .ip4 = net.Ip4Address.loopback(port) };
    const stream = try dest.connect(io, .{ .mode = .stream });
    defer stream.close(io);
    var rbuf: [64]u8 = undefined;
    var wbuf: [64]u8 = undefined;
    var r = stream.reader(io, &rbuf);
    var w = stream.writer(io, &wbuf);
    try w.interface.writeAll("hola\n");
    try w.interface.flush();
    const reply = try r.interface.takeDelimiterExclusive('\n');
    try std.testing.expectEqualStrings("eco:hola", reply);
    try srv.await(io);
}

test "conectar a un puerto sin servidor falla con ConnectionRefused" {
    var threaded: std.Io.Threaded = .init(std.testing.allocator, .{});
    defer threaded.deinit();
    const io = threaded.io();
    // abrir y cerrar un listener para obtener un puerto que seguro esta libre
    const any = net.IpAddress{ .ip4 = net.Ip4Address.loopback(0) };
    var server = try any.listen(io, .{ .reuse_address = true });
    const port = server.socket.address.getPort();
    server.deinit(io);
    const dest = net.IpAddress{ .ip4 = net.Ip4Address.loopback(port) };
    try std.testing.expectError(error.ConnectionRefused, dest.connect(io, .{ .mode = .stream }));
}
''',
         apis_used=['std.Io.net.IpAddress.listen', 'std.Io.net.IpAddress.connect', 'std.Io.net.Ip4Address.loopback', 'std.Io.net.Server.accept', 'std.Io.net.Server.deinit', 'std.Io.net.Stream.reader', 'std.Io.net.Stream.writer', 'std.Io.net.Stream.close', 'std.Io.Reader.takeDelimiterExclusive', 'std.Io.concurrent'],
         constraints=['solo loopback 127.0.0.1', 'puerto 0 (efimero)', 'requiere stack de red local del SO'],
         preconditions=['el puerto efimero se lee de server.socket.address.getPort() ANTES de lanzar al cliente'],
         postconditions=['la conexion y los sockets quedan cerrados al salir (defer)'],
         side_effects=['abre sockets en loopback'],
         error_behavior='listen/connect/accept devuelven errores tipados (AddressInUse, ConnectionRefused, Timeout, SocketNotListening, ...); un servidor que falla se ve en srv.await(io).',
         ownership_memory='Los buffers de reader/writer los aporta el llamador y deben vivir lo que viva el reader/writer; takeDelimiterExclusive devuelve un slice DENTRO del buffer del reader (invalido tras la siguiente lectura). El Server, el Stream y el Io deben cerrarse con deinit/close; el cierre del servidor ocurre despues de esperar su tarea.',
         differences=['No hay bind()+listen() por separado: IpAddress.listen hace socket+bind+listen; el puerto real tras puerto 0 esta en server.socket.address.getPort() (equivale a getsockname()[1])', 'accept() BLOQUEA: si el servidor y el cliente van en el mismo hilo, accept nunca vuelve antes de connect. Hay que lanzar el servidor con io.concurrent (no io.async, que puede ejecutar inline y bloquear el test para siempre)', 'No existe socket.sendall/recv: se usa Stream.writer/reader con buffer propio; hay que llamar a w.interface.flush() o los bytes nunca salen', "reader.takeDelimiterExclusive('\\n') devuelve la linea SIN el salto y como slice del buffer del reader, no una copia; si la linea no cabe en el buffer, falla con StreamTooLong", 'reuse_address (SO_REUSEADDR) es una opcion de listen; por defecto esta apagada, al reves que muchos ejemplos de Python', 'Los errores de red son un conjunto tipado (error.ConnectionRefused) en vez de ConnectionRefusedError con errno', 'Orden de cierre: esperar (await) la tarea servidor antes de cerrar su Server; stream.close del cliente y server.deinit son independientes y ambos hay que hacerlos'],
         provenance=PROV),
    dict(operation_id='zig0.16/udp-loopback-datagram',
         name='datagramas UDP en loopback (socket SOCK_DGRAM sendto/recvfrom)',
         intent='Enviar y recibir un datagrama UDP entre dos sockets de 127.0.0.1 con puerto efimero en un mismo test, con timeout de recepcion.',
         aliases=['socket.SOCK_DGRAM', 'sock.sendto', 'sock.recvfrom', 'socket.settimeout', 'UDP', 'datagramas', 'udp socket', 'enviar un paquete UDP', 'recibir datagrama', 'loopback udp', 'asyncio.DatagramProtocol'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref=r'''import socket
rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); rx.bind(("127.0.0.1", 0)); rx.settimeout(2)
tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); tx.bind(("127.0.0.1", 0))
tx.sendto(b"ping", rx.getsockname())
data, addr = rx.recvfrom(32)''',
         zig_impl=r'''const net = std.Io.net;

fn udpRoundTrip(io: std.Io, payload: []const u8, out: []u8) ![]const u8 {
    const any = net.IpAddress{ .ip4 = net.Ip4Address.loopback(0) };
    const rx = try any.bind(io, .{ .mode = .dgram });
    defer rx.close(io);
    const tx = try any.bind(io, .{ .mode = .dgram });
    defer tx.close(io);
    const dest = net.IpAddress{ .ip4 = net.Ip4Address.loopback(rx.address.getPort()) };
    try tx.send(io, &dest, payload);
    const msg = try rx.receiveTimeout(io, out, .{ .duration = .{ .raw = .fromSeconds(2), .clock = .awake } });
    return msg.data;
}''',
         zig_test=r'''const std = @import("std");

const net = std.Io.net;

fn udpRoundTrip(io: std.Io, payload: []const u8, out: []u8) ![]const u8 {
    const any = net.IpAddress{ .ip4 = net.Ip4Address.loopback(0) };
    const rx = try any.bind(io, .{ .mode = .dgram });
    defer rx.close(io);
    const tx = try any.bind(io, .{ .mode = .dgram });
    defer tx.close(io);
    const dest = net.IpAddress{ .ip4 = net.Ip4Address.loopback(rx.address.getPort()) };
    try tx.send(io, &dest, payload);
    const msg = try rx.receiveTimeout(io, out, .{ .duration = .{ .raw = .fromSeconds(2), .clock = .awake } });
    return msg.data;
}

test "UDP loopback: bind puerto 0, send y receive" {
    var threaded: std.Io.Threaded = .init(std.testing.allocator, .{});
    defer threaded.deinit();
    const io = threaded.io();
    var buf: [32]u8 = undefined;
    const got = try udpRoundTrip(io, "ping", &buf);
    try std.testing.expectEqualStrings("ping", got);
}

test "receiveTimeout: sin datos vence con Timeout" {
    var threaded: std.Io.Threaded = .init(std.testing.allocator, .{});
    defer threaded.deinit();
    const io = threaded.io();
    const any = net.IpAddress{ .ip4 = net.Ip4Address.loopback(0) };
    const rx = try any.bind(io, .{ .mode = .dgram });
    defer rx.close(io);
    var buf: [8]u8 = undefined;
    const r = rx.receiveTimeout(io, &buf, .{ .duration = .{ .raw = .fromMilliseconds(50), .clock = .awake } });
    try std.testing.expectError(error.Timeout, r);
}

test "el origen del datagrama (from) es el puerto del emisor" {
    var threaded: std.Io.Threaded = .init(std.testing.allocator, .{});
    defer threaded.deinit();
    const io = threaded.io();
    const any = net.IpAddress{ .ip4 = net.Ip4Address.loopback(0) };
    const rx = try any.bind(io, .{ .mode = .dgram });
    defer rx.close(io);
    const tx = try any.bind(io, .{ .mode = .dgram });
    defer tx.close(io);
    const dest = net.IpAddress{ .ip4 = net.Ip4Address.loopback(rx.address.getPort()) };
    try tx.send(io, &dest, "x");
    var buf: [8]u8 = undefined;
    const msg = try rx.receiveTimeout(io, &buf, .{ .duration = .{ .raw = .fromSeconds(2), .clock = .awake } });
    try std.testing.expectEqual(tx.address.getPort(), msg.from.getPort());
}
''',
         apis_used=['std.Io.net.IpAddress.bind', 'std.Io.net.Socket.send', 'std.Io.net.Socket.receiveTimeout', 'std.Io.net.Socket.close', 'std.Io.net.IncomingMessage', 'std.Io.Timeout'],
         constraints=['solo loopback 127.0.0.1', 'puerto 0 (efimero)'],
         preconditions=['el buffer de recepcion es al menos tan grande como el datagrama (si no se trunca)'],
         postconditions=['los dos sockets se cierran al salir'],
         side_effects=['abre sockets UDP en loopback'],
         error_behavior='receiveTimeout devuelve error.Timeout si no llega nada a tiempo; send y bind devuelven errores tipados.',
         ownership_memory='IncomingMessage.data es un slice del buffer que aporta el llamador: vale lo que viva ese buffer y se sobrescribe en la siguiente recepcion. Cada Socket se cierra con close(io).',
         differences=['sendto/recvfrom son Socket.send(io, &dest, data) y Socket.receive*(io, buf) -> IncomingMessage (data + from + flags); no hay tupla (data, addr)', 'settimeout() de Python es estado del socket; en Zig el plazo es un argumento de cada llamada (receiveTimeout con Io.Timeout); receive() sin plazo bloquea para siempre', 'El mismo socket enlazado a puerto 0 sirve para enviar y recibir: el puerto real queda en socket.address.getPort()', 'Un datagrama mas grande que el buffer se trunca (Flags.trunc) en vez de fallar; un datagrama es un mensaje entero, no un flujo', 'UDP no garantiza entrega: en loopback es fiable en la practica, pero el test usa timeout para no colgarse si se pierde', 'Orden de cierre: ambos sockets son independientes y se cierran con defer; enviar a un puerto ya cerrado puede dar ConnectionRefused en la siguiente llamada, no en la actual'],
         provenance=PROV),
    dict(operation_id='zig0.16/http-client-get-local',
         name='cliente HTTP GET contra un servidor HTTP minimo (urllib/requests.get)',
         intent='Hacer una peticion HTTP GET con std.http.Client contra un servidor std.http.Server levantado en el mismo test en 127.0.0.1, y leer estado y cuerpo.',
         aliases=['requests.get', 'urllib.request.urlopen', 'http.client.HTTPConnection', 'http.server.HTTPServer', 'BaseHTTPRequestHandler', 'cliente HTTP', 'descargar una URL', 'GET a una URL', 'respuesta HTTP status y cuerpo', 'servidor HTTP minimo', 'httpx.get', 'raise_for_status'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref=r'''import threading, http.server, urllib.request
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.handle_request).start()
r = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/hola")
r.status, r.read()''',
         zig_impl=r'''const net = std.Io.net;

fn serveOne(io: std.Io, server: *net.Server) !void {
    const conn = try server.accept(io);
    defer conn.close(io);
    var rbuf: [2048]u8 = undefined;
    var wbuf: [2048]u8 = undefined;
    var r = conn.reader(io, &rbuf);
    var w = conn.writer(io, &wbuf);
    var http_server = std.http.Server.init(&r.interface, &w.interface);
    var req = try http_server.receiveHead();
    if (std.mem.eql(u8, req.head.target, "/hola")) {
        try req.respond("{\"ok\":true}", .{
            .extra_headers = &.{.{ .name = "content-type", .value = "application/json" }},
            .keep_alive = false,
        });
    } else {
        try req.respond("no existe", .{ .status = .not_found, .keep_alive = false });
    }
}

fn get(gpa: std.mem.Allocator, io: std.Io, url: []const u8, out: *std.Io.Writer.Allocating) !std.http.Status {
    var client: std.http.Client = .{ .allocator = gpa, .io = io };
    defer client.deinit();
    const res = try client.fetch(.{
        .location = .{ .url = url },
        .response_writer = &out.writer,
        .keep_alive = false,
    });
    return res.status;
}''',
         zig_test=r'''const std = @import("std");

const net = std.Io.net;

fn serveOne(io: std.Io, server: *net.Server) !void {
    const conn = try server.accept(io);
    defer conn.close(io);
    var rbuf: [2048]u8 = undefined;
    var wbuf: [2048]u8 = undefined;
    var r = conn.reader(io, &rbuf);
    var w = conn.writer(io, &wbuf);
    var http_server = std.http.Server.init(&r.interface, &w.interface);
    var req = try http_server.receiveHead();
    if (std.mem.eql(u8, req.head.target, "/hola")) {
        try req.respond("{\"ok\":true}", .{
            .extra_headers = &.{.{ .name = "content-type", .value = "application/json" }},
            .keep_alive = false,
        });
    } else {
        try req.respond("no existe", .{ .status = .not_found, .keep_alive = false });
    }
}

fn get(gpa: std.mem.Allocator, io: std.Io, url: []const u8, out: *std.Io.Writer.Allocating) !std.http.Status {
    var client: std.http.Client = .{ .allocator = gpa, .io = io };
    defer client.deinit();
    const res = try client.fetch(.{
        .location = .{ .url = url },
        .response_writer = &out.writer,
        .keep_alive = false,
    });
    return res.status;
}

test "GET contra un servidor HTTP minimo en el mismo test" {
    const gpa = std.testing.allocator;
    var threaded: std.Io.Threaded = .init(gpa, .{});
    defer threaded.deinit();
    const io = threaded.io();

    const any = net.IpAddress{ .ip4 = net.Ip4Address.loopback(0) };
    var server = try any.listen(io, .{ .reuse_address = true });
    defer server.deinit(io);
    const port = server.socket.address.getPort();

    var srv = try io.concurrent(serveOne, .{ io, &server });

    var url_buf: [64]u8 = undefined;
    const url = try std.fmt.bufPrint(&url_buf, "http://127.0.0.1:{d}/hola", .{port});
    var body: std.Io.Writer.Allocating = .init(gpa);
    defer body.deinit();
    const status = try get(gpa, io, url, &body);
    try srv.await(io);
    try std.testing.expectEqual(std.http.Status.ok, status);
    try std.testing.expectEqualStrings("{\"ok\":true}", body.written());
}

test "un 404 NO es un error de Zig (a diferencia de raise_for_status)" {
    const gpa = std.testing.allocator;
    var threaded: std.Io.Threaded = .init(gpa, .{});
    defer threaded.deinit();
    const io = threaded.io();
    const any = net.IpAddress{ .ip4 = net.Ip4Address.loopback(0) };
    var server = try any.listen(io, .{ .reuse_address = true });
    defer server.deinit(io);
    var srv = try io.concurrent(serveOne, .{ io, &server });
    var url_buf: [64]u8 = undefined;
    const url = try std.fmt.bufPrint(&url_buf, "http://127.0.0.1:{d}/otra", .{server.socket.address.getPort()});
    var body: std.Io.Writer.Allocating = .init(gpa);
    defer body.deinit();
    const status = try get(gpa, io, url, &body);
    try srv.await(io);
    try std.testing.expectEqual(std.http.Status.not_found, status);
    try std.testing.expectEqualStrings("no existe", body.written());
}
''',
         apis_used=['std.http.Client', 'std.http.Client.fetch', 'std.http.Client.deinit', 'std.http.Server.init', 'std.http.Server.receiveHead', 'std.http.Server.Request.respond', 'std.Io.Writer.Allocating', 'std.Io.net.IpAddress.listen', 'std.Io.concurrent'],
         constraints=['solo loopback 127.0.0.1', 'puerto 0 (efimero)', 'sin TLS ni DNS'],
         preconditions=['el servidor ya esta escuchando (listen) antes de que el cliente conecte; el puerto se lee antes de formar la URL'],
         postconditions=['cuerpo y estado quedan disponibles; cliente y servidor cerrados'],
         side_effects=['abre sockets TCP en loopback'],
         error_behavior='fetch devuelve error tipado si falla la conexion o el protocolo; un estado 4xx/5xx NO es error: viene en FetchResult.status.',
         ownership_memory='El cuerpo se escribe en un std.Io.Writer.Allocating del llamador (liberar con deinit; written() es un slice suyo). El Client necesita allocator e Io y se libera con deinit. Los buffers de reader/writer del servidor deben vivir toda la peticion; los headers de Request apuntan a su head_buffer y se invalidan al leer el cuerpo.',
         differences=['Un 404/500 NO lanza excepcion: fetch devuelve el status y hay que comprobarlo a mano (equivalente a no llamar nunca a raise_for_status)', 'fetch NO devuelve el cuerpo: lo escribe en un Writer que el llamador aporta (response_writer); si es null, se descarta. Hay que dar un Writer.Allocating y leer .written() ANTES de liberarlo', 'std.http.Client exige .allocator y .io en su inicializacion y NO soporta TLS en este test (http plano); con https y DNS se requiere red/certificados, fuera de lo hermetico', 'Servidor y cliente en el mismo proceso: el servidor DEBE correr en otra tarea (io.concurrent); con io.async podria ejecutarse inline y bloquear en accept antes de que el cliente conecte', 'Con keep_alive=true el cliente deja la conexion abierta y client.deinit la cierra: si el servidor solo atiende una peticion, usar keep_alive=false en ambos lados o el cierre espera', 'std.http.Server atiende UNA conexion por Server.init con tus reader/writer; no hay bucle serve_forever ni hilo por conexion: los haces tu', 'Orden de cierre: await del servidor antes de comprobar resultados, y deinit del Client antes de deinit del Io.Threaded'],
         provenance=PROV),
    dict(operation_id='zig0.16/ffi-extern-c-function',
         name='llamar a una funcion C (ctypes.CDLL / FFI) con extern fn, sin @cImport',
         intent='Declarar una funcion de libc o de otra biblioteca C con extern y llamarla; en un test hermetico, un simbolo C-ABI propio exportado con @export.',
         aliases=['ctypes.CDLL', 'ctypes.cdll.LoadLibrary', 'ctypes.c_int', 'libc.abs', 'libc.strlen', 'cffi', 'FFI', 'llamar a una funcion de C', 'extern fn', 'enlazar libc', 'callconv(.c)', 'ctypes.CFUNCTYPE', '@cImport alternativa'],
         source_lang="python", target_lang="zig", zig_version=ZIG, python_version=PY, platform="linux",
         py_ref=r'''import ctypes
libc = ctypes.CDLL(None)
libc.abs.argtypes = [ctypes.c_int]; libc.abs.restype = ctypes.c_int
libc.abs(-5)                      # 5
libc.strlen(b"abcd")              # 4''',
         zig_impl=r'''// Simbolo C-ABI definido en esta misma unidad (no necesita libc): extern lo resuelve el enlazador.
fn sumaImpl(a: c_int, b: c_int) callconv(.c) c_int {
    return a + b;
}
comptime {
    @export(&sumaImpl, .{ .name = "pyzig_suma" });
}
extern fn pyzig_suma(c_int, c_int) c_int;

// Funciones de libc: solo se referencian si el binario se enlaza con libc (zig test -lc).
const libc = if (builtin.link_libc) struct {
    extern "c" fn abs(c_int) c_int;
    extern "c" fn strlen([*:0]const u8) usize;
} else struct {};''',
         zig_test=r'''const std = @import("std");
const builtin = @import("builtin");

// Simbolo C-ABI definido en esta misma unidad (no necesita libc): extern lo resuelve el enlazador.
fn sumaImpl(a: c_int, b: c_int) callconv(.c) c_int {
    return a + b;
}
comptime {
    @export(&sumaImpl, .{ .name = "pyzig_suma" });
}
extern fn pyzig_suma(c_int, c_int) c_int;

// Funciones de libc: solo se referencian si el binario se enlaza con libc (zig test -lc).
const libc = if (builtin.link_libc) struct {
    extern "c" fn abs(c_int) c_int;
    extern "c" fn strlen([*:0]const u8) usize;
} else struct {};

test "extern fn hacia un simbolo C-ABI de esta unidad" {
    try std.testing.expectEqual(@as(c_int, 7), pyzig_suma(3, 4));
}

test "tipos C: c_int es 32 bits y c_long el ancho de la plataforma" {
    try std.testing.expectEqual(@as(usize, 4), @sizeOf(c_int));
    try std.testing.expectEqual(@as(usize, @sizeOf(usize)), @sizeOf(c_long));
}

test "libc: abs y strlen (solo con zig test -lc)" {
    if (!builtin.link_libc) return error.SkipZigTest;
    try std.testing.expectEqual(@as(c_int, 5), libc.abs(-5));
    try std.testing.expectEqual(@as(usize, 4), libc.strlen("abcd"));
}
''',
         apis_used=['extern fn', 'extern "c"', '@export', 'callconv(.c)', 'builtin.link_libc', 'c_int', 'c_long'],
         constraints=['sin red', 'las llamadas a libc exigen enlazar libc explicitamente (-lc o exe.linkLibC())'],
         preconditions=['la firma extern coincide EXACTAMENTE con la C (Zig no la comprueba)'],
         postconditions=['el simbolo se resuelve en tiempo de enlace'],
         side_effects=['las llamadas C pueden tener efectos arbitrarios'],
         error_behavior='Una firma equivocada es comportamiento indefinido, no un error. Sin -lc, un extern "c" falla en COMPILACION: "dependency on libc must be explicitly specified in the build command".',
         ownership_memory='Los punteros pasados a C son [*:0]const u8 (terminados en 0), no slices: un literal Zig ya lo es; para []const u8 hay que copiar a un buffer con centinela. La memoria que C devuelva se libera con la funcion de C correspondiente, no con el allocator de Zig.',
         differences=['ctypes carga y resuelve simbolos en TIEMPO DE EJECUCION (CDLL, dlopen); Zig los resuelve en TIEMPO DE ENLACE: un simbolo ausente es un error de enlace, no AttributeError', "zig test normal NO enlaza libc: 'extern c fn abs' falla al compilar con 'dependency on libc must be explicitly specified'. Hay que ejecutar `zig test -lc` o, en build.zig, exe.linkLibC(). El gate de este repo corre `zig test` SIN -lc, asi que el test de libc se salta (SkipZigTest) y solo el simbolo C-ABI propio queda demostrado por el gate; la rama -lc se verifico a mano (zig test -lc: all passed)", 'No hay argtypes/restype que se puedan olvidar y fallar en silencio: la firma extern ES la declaracion; pero Zig no la valida contra la cabecera C, una firma equivocada es UB', 'Los strings: C espera [*:0]const u8 (puntero con centinela); un []const u8 de Zig no vale. Los literales Zig se coercionan; los slices dinamicos requieren copia con terminador (allocator.dupeZ)', 'Usa los tipos c_int/c_long/c_char, no i32/i64: su ancho depende de la plataforma (c_long es 64 bits en Linux x86_64, 32 en Windows)', '@cImport esta deprecado en 0.16: la via recomendada es declarar los extern a mano o usar b.addTranslateC en build.zig', 'Para exportar una funcion Zig a C se usa callconv(.c) mas @export(&fn, .{ .name = ... }) (o export fn); ctypes.CFUNCTYPE para callbacks no tiene equivalente directo: un callback es un fn callconv(.c) normal'],
         provenance=PROV),
]

CONTRACTS = {
    "zig0.16/thread-spawn-join": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/thread-shared-counter": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/io-async-group-future": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/tcp-loopback-echo": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/udp-loopback-datagram": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/http-client-get-local": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
    "zig0.16/ffi-extern-c-function": _c(None, None, None, [],
        type_sig={"input": "ver zig_impl", "output": "ver zig_impl"},
        skip_reason="sin driver diferencial todavia"),
}
