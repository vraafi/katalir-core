// F3.3 sandbox host. Runs user JS in a bare vm context with no Node globals and
// no require/import, then serves the two things it needs from Python over
// stdin/stdout instead.
//
// Why fetch is proxied to Python rather than implemented here: node's fetch can
// reach anything, including 169.254.169.254, and re-implementing a blocklist in
// JS means a second one to drift from katalir_protocols/ssrf.py. So the sandbox
// has no network of its own. It emits a request, Python applies the guard, and
// an unapproved host never leaves this process.
//
// The stdout discipline matters: this is a line protocol. Any stray console.log
// or user print would desynchronise it, so console is replaced and stdout writes
// are funnelled through the same emit() the protocol uses.

'use strict';
const vm = require('node:vm');
const readline = require('node:readline');

let seq = 0;
function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

function makeConsole() {
  const push = (level) => (...parts) => {
    emit({ kind: 'log', level, text: parts.map((p) => {
      try { return typeof p === 'string' ? p : JSON.stringify(p); }
      catch { return String(p); }
    }).join(' ') });
  };
  return { log: push('log'), info: push('info'), warn: push('warn'), error: push('error'), debug: push('debug') };
}

// __katalir_fetch: the only egress in the sandbox.
async function sandboxFetch(url, init) {
  const id = ++seq;
  const opts = (init && typeof init === 'object') ? init : {};
  emit({
    kind: 'request',
    id,
    url: String(url),
    method: String(opts.method || 'GET').toUpperCase(),
    headers: (opts.headers && typeof opts.headers === 'object') ? opts.headers : {},
    body: typeof opts.body === 'string' ? opts.body : null,
  });
  const reply = await waitFor(id);
  return makeResponse(reply);
}

function makeResponse(r) {
  return {
    ok: r.status >= 200 && r.status < 300,
    status: r.status,
    async text() { return r.text; },
    async json() { return JSON.parse(r.text); },
  };
}

const pending = new Map();
function waitFor(id) {
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        reject(new Error('fetch timed out'));
      }
    }, 20000).unref();
  });
}

const rl = readline.createInterface({ input: process.stdin });
rl.on('line', (line) => {
  let msg;
  try { msg = JSON.parse(line); } catch { return; }
  const p = pending.get(msg.id);
  if (!p) return;
  pending.delete(msg.id);
  if (msg.kind === 'error') p.reject(new Error(String(msg.error || 'fetch failed')));
  else p.resolve(msg);
});

// Globals: no process, no require, no Buffer, no setImmediate. Async is present
// because a fetch tool without await is useless, and Promise is safe to expose.
const sandbox = {
  fetch: sandboxFetch,
  console: makeConsole(),
  JSON, Math, Date, URL, URLSearchParams, TextEncoder, TextDecoder,
  Promise, Array, Object, String, Number, Boolean, RegExp, Map, Set, Error,
  parseInt, parseFloat, isNaN, encodeURIComponent, decodeURIComponent,
  setTimeout, clearTimeout,
};
sandbox.globalThis = sandbox;

const context = vm.createContext(sandbox, { codeGeneration: { strings: false, wasm: false } });

rl.on('line', function first(line) {
  // The first line is the program itself; every later line is a fetch reply.
  rl.off('line', first);
  (async () => {
    let src = '';
    try { src = JSON.parse(line).code || ''; } catch (e) { emit({ kind: 'error', error: 'bad envelope' }); process.exit(0); }
    emit({ kind: 'ready' });
    const t0 = Date.now();
    try {
      const result = await vm.runInContext(`(async () => { ${src} })()`, context, {
        timeout: 5000, displayErrors: true, breakOnSigint: true,
      });
      emit({ kind: 'done', ms: Date.now() - t0, value: result === undefined ? null : result });
    } catch (err) {
      emit({ kind: 'error', ms: Date.now() - t0, error: String((err && err.message) || err) });
    }
    process.exit(0);
  })();
});

emit({ kind: 'booted', pid: process.pid });
