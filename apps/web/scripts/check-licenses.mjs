// License gate for the web app's npm closure (same policy as license-policy.toml).
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const ALLOWED = new Set(["MIT", "MIT-0", "ISC", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "Apache-2.0",
  "Zlib", "Unlicense", "CC0-1.0", "BlueOak-1.0.0", "Python-2.0", "CC-BY-4.0"]);
const DENIED = /(^|\W)(A?GPL|LGPL|SSPL|BUSL|CC-BY-NC|Commons-Clause)/i;

function packages(dir) {
  const out = [];
  if (!existsSync(dir)) return out;
  for (const name of readdirSync(dir)) {
    if (name.startsWith(".")) continue;
    const path = join(dir, name);
    if (name.startsWith("@")) { out.push(...packages(path)); continue; }
    const manifest = join(path, "package.json");
    if (existsSync(manifest)) out.push(JSON.parse(readFileSync(manifest, "utf8")));
    out.push(...packages(join(path, "node_modules")));
  }
  return out;
}

function ok(expr) {
  if (!expr || typeof expr !== "string") return false;
  if (DENIED.test(expr)) return false;
  // "(MIT OR Apache-2.0)": one allowed alternative is enough; "A AND B": all must be allowed.
  const clean = expr.replace(/[()]/g, " ").trim();
  if (/ OR /.test(clean)) return clean.split(/ OR /).some((p) => ok(p.trim()));
  return clean.split(/ AND /).every((p) => ALLOWED.has(p.trim()));
}

const all = packages("node_modules");
const bad = all.filter((p) => !ok(typeof p.license === "string" ? p.license : p.license?.type));
for (const p of bad) console.log(`VIOLATION ${p.name}@${p.version}: ${JSON.stringify(p.license)}`);
console.log(`${all.length} npm packages checked, ${bad.length} violations`);
process.exit(bad.length ? 1 : 0);
