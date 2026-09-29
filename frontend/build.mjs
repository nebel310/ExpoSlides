import { build } from "esbuild";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";

const output = new URL("../exposlides/studio_static/", import.meta.url);
await mkdir(output, { recursive: true });
await build({
  entryPoints: ["src/main.tsx"], bundle: true, minify: true, sourcemap: false,
  outfile: new URL("app.js", output).pathname,
  target: ["chrome120", "firefox121", "safari17"], jsx: "automatic",
  define: { "process.env.NODE_ENV": '"production"' },
  legalComments: "eof",
});
// URL меняется вместе с содержимым: браузер не переиспользует старый bundle после деплоя.
let html = await readFile(new URL("index.html", import.meta.url), "utf8");
for (const name of ["app.js", "app.css"]) {
  const bytes = await readFile(new URL(name, output));
  const version = createHash("sha256").update(bytes).digest("hex").slice(0, 16);
  html = html.replace(`/${name}"`, `/${name}?v=${version}"`);
}
await writeFile(new URL("index.html", output), html);
console.log("Studio built into exposlides/studio_static");
