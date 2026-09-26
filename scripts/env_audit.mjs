/**
 * Structural health check for a .env file. Prints line numbers, classes, key
 * NAMES and value LENGTHS only - never a value. Safe to paste output into a
 * ticket or a chat without leaking anything.
 *
 *   node scripts/env_audit.mjs            # audits ./.env
 *   node scripts/env_audit.mjs path/to/.env
 *
 * Exits non-zero when the file is unhealthy, so it can be a CI gate.
 *
 * Why this exists: a pasted chat message once landed in .env. A non-conforming
 * line is the dangerous kind of corruption here, because python-dotenv does not
 * warn about it - if the line starts with a letter it is silently accepted as an
 * environment variable whose NAME is the stray text. Any env dump then leaks it.
 */
import { readFileSync } from "node:fs";

const FILE = process.argv[2] || ".env";
const KEY_RE = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$/;

let raw;
try {
  raw = readFileSync(FILE);
} catch {
  console.error(`cannot read ${FILE}`);
  process.exit(2);
}

const hasBOM = raw.length >= 3 && raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf;
const text = raw.toString("utf8");
const crlf = /\r\n/.test(text);
const lines = text.split(/\r?\n/);
if (lines.length && lines[lines.length - 1] === "") lines.pop();

const counts = { blank: 0, comment: 0, key: 0, junk: 0 };
const junk = [];
const keys = [];
let openQuote = null;

lines.forEach((line, i) => {
  const t = line.trim();
  if (t === "") return void counts.blank++;
  if (t.startsWith("#")) return void counts.comment++;
  const m = line.match(KEY_RE);
  if (m) {
    counts.key++;
    keys.push({ n: i + 1, key: m[1], value: m[2] });
    for (const ch of m[2]) {
      if (ch === '"' || ch === "'") openQuote = openQuote === ch ? null : (openQuote ?? ch);
    }
    return;
  }
  counts.junk++;
  junk.push({ n: i + 1, len: t.length });
});

const seen = new Set();
const dupes = keys.filter((k) => (seen.has(k.key) ? true : (seen.add(k.key), false))).map((k) => k.key);
const empties = keys.filter((k) => k.value.trim() === "").map((k) => k.key);

console.log(`FILE=${FILE}`);
console.log(`LINES=${lines.length} BYTES=${raw.length}`);
console.log(`BOM=${hasBOM} CRLF=${crlf} TRAILING_NEWLINE=${/\n$/.test(text)}`);
console.log(`COUNTS blank=${counts.blank} comment=${counts.comment} key=${counts.key} JUNK=${counts.junk}`);
console.log(`UNTERMINATED_QUOTE=${openQuote ? `YES(${openQuote})` : "no"}`);
console.log(`DUPLICATE_KEYS=${dupes.length ? dupes.join("; ") : "none"}`);
console.log(`EMPTY_VALUES=${empties.length ? empties.join(", ") : "none"}`);
if (junk.length) {
  console.log(`NON_CONFORMING_LINES (comment these out, do not delete blindly):`);
  for (const j of junk) console.log(`  line ${j.n}: ${j.len} chars`);
}

const bad = [];
if (hasBOM) bad.push("BOM present - strip it, some loaders keep it as part of the first key name");
if (counts.junk) bad.push(`${counts.junk} non-conforming line(s)`);
if (openQuote) bad.push(`unterminated ${openQuote} quote`);
if (dupes.length) bad.push(`duplicate keys: ${dupes.join(", ")}`);

if (bad.length) {
  console.log(`\nUNHEALTHY: ${bad.join("; ")}`);
  process.exit(1);
}
console.log(`\nOK: ${keys.length} keys, no parse hazards.`);
