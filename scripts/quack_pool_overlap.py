#!/usr/bin/env python3
"""Check whether DuckLake's metadata statements on a quack catalog overlap on the wire.

DuckLake serializes the metadata statements of every transaction behind one catalog lock unless the quack
metadata catalog pins each transaction to a connection of its own (a quack client with pool_size > 1). This
script puts a counting proxy between DuckLake and a quack server, runs concurrent readers and reports how many
metadata requests (PREPARE/FETCH, without quack's own bare BEGIN/COMMIT/ROLLBACK) were in flight at once.

    --expect serial      fail unless at most one metadata request was ever in flight (unpooled)
    --expect concurrent  fail unless metadata requests overlapped (pooled)

Needs the duckdb Python package matching the build, plus the quack (with pool_size), httpfs and ducklake
extension files. Example:

    scripts/quack_pool_overlap.py --duckdb build/release/duckdb --quack quack.duckdb_extension \\
        --httpfs httpfs.duckdb_extension --ducklake build/release/extension/ducklake/ducklake.duckdb_extension \\
        --pool-size 1 --expect serial
"""

import argparse, collections, http.client, http.server, os, socket, subprocess, sys, tempfile, threading, time

import duckdb

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('--duckdb', required=True, help='duckdb CLI that runs the quack server')
p.add_argument('--quack', required=True)
p.add_argument('--httpfs', required=True)
p.add_argument('--ducklake', required=True)
p.add_argument('--pool-size', type=int, default=1)
p.add_argument('--readers', type=int, default=8)
p.add_argument('--seconds', type=float, default=5)
p.add_argument('--port', type=int, default=19751, help='server port; the proxy listens on port + 1')
p.add_argument('--expect', choices=['serial', 'concurrent'])
args = p.parse_args()

TOKEN = 'overlap-token'
failed = True
work = tempfile.mkdtemp(prefix='quack_pool_overlap_')
server = subprocess.Popen(
    [args.duckdb, '-unsigned', os.path.join(work, 'server.db')], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL, text=True)
server.stdin.write(f"LOAD '{args.httpfs}'; LOAD '{args.quack}'; LOAD ducklake;\n"
                   f"SELECT * FROM quack_serve('quack:127.0.0.1:{args.port}', token := '{TOKEN}');\n")
server.stdin.flush()

state = {'inflight': 0, 'max': 0, 'busy': 0.0, 'last': None, 'requests': 0, 'on': False}
lock = threading.Lock()
local = threading.local()


def is_metadata(body):
    kind = body[2] if len(body) > 2 else 0  # message type: 3 = PREPARE_REQUEST, 7 = FETCH_REQUEST
    if kind not in (3, 7):
        return False
    if kind == 3 and len(body) < 160 and any(k in body for k in (b'BEGIN TRANSACTION', b'COMMIT', b'ROLLBACK')):
        return any(k in body for k in (b'SELECT', b'INSERT', b'UPDATE', b'DELETE'))
    return True


def tick(delta):
    now = time.monotonic()
    if state['on'] and state['inflight'] > 0:
        state['busy'] += (now - state['last']) * state['inflight']
    state['last'] = now
    state['inflight'] += delta
    if state['on']:
        state['max'] = max(state['max'], state['inflight'])
        state['requests'] += delta > 0


class Proxy(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        metadata = is_metadata(body)
        if metadata:
            with lock:
                tick(+1)
        try:
            if not hasattr(local, 'upstream'):
                local.upstream = http.client.HTTPConnection('127.0.0.1', args.port, timeout=600)
                local.upstream.connect()
                local.upstream.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in ('host', 'content-length')}
            local.upstream.request('POST', self.path, body=body, headers=headers)
            response = local.upstream.getresponse()
            data = response.read()
        finally:
            if metadata:
                with lock:
                    tick(-1)
        self.send_response(response.status)
        for k, v in response.getheaders():
            if k.lower() not in ('content-length', 'transfer-encoding', 'connection'):
                self.send_header(k, v)
        self.send_header('Content-Length', str(len(data)))
        self._headers_buffer += [b'\r\n', data]  # one write: no Nagle stall between headers and body
        self.flush_headers()

    def log_message(self, *a):
        pass


try:
    proxy = http.server.ThreadingHTTPServer(('127.0.0.1', args.port + 1), Proxy)
    proxy.daemon_threads = True
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(('127.0.0.1', args.port), timeout=0.1).close()
            break
        except OSError:
            time.sleep(0.1)

    db = duckdb.connect(config={'allow_unsigned_extensions': 'true'})
    for ext in (args.httpfs, args.quack, args.ducklake):
        db.execute(f"LOAD '{ext}'")
    db.execute(f"CREATE SECRET (TYPE QUACK, TOKEN '{TOKEN}')")
    db.execute(f"ATTACH 'ducklake:quack:127.0.0.1:{args.port + 1}' AS dl (DATA_PATH '{work}/data', "
               f"METADATA_PARAMETERS MAP {{'DISABLE_SSL': '1', 'pool_size': '{args.pool_size}'}})")
    db.execute("CREATE TABLE dl.t(i INTEGER)")
    db.execute("INSERT INTO dl.t VALUES (1)")

    ok, errors = [0], collections.Counter()

    def reader():
        cursor = db.cursor()
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            try:
                cursor.execute("SELECT count(*) FROM dl.t").fetchall()
                with lock:
                    ok[0] += 1
            except Exception as ex:
                with lock:
                    errors[str(ex).splitlines()[0][:120]] += 1

    with lock:
        state.update(on=True, last=time.monotonic())
    start = time.monotonic()
    threads = [threading.Thread(target=reader) for _ in range(args.readers)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with lock:
        tick(0)
        state['on'] = False
    wall = time.monotonic() - start
    print(f"pool_size={args.pool_size} readers={args.readers}: {ok[0] / wall:.0f} ops/s, "
          f"{state['requests']} metadata requests, max in flight {state['max']}, "
          f"average concurrency {state['busy'] / wall:.2f}, errors {sum(errors.values())}")
    for message, count in errors.most_common(3):
        print('   ', count, message)
    failed = bool(errors) or (args.expect == 'serial' and state['max'] != 1) or \
        (args.expect == 'concurrent' and state['max'] < 2)
    print('FAIL' if failed else 'OK')
    sys.stdout.flush()
finally:
    server.kill()
    server.wait()
os._exit(1 if failed else 0)  # skip interpreter teardown of the still-attached catalog
