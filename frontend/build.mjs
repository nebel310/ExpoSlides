import { build } from "esbuild";
import { mkdir, copyFile } from "node:fs/promises";

const output = new URL("../exposlides/studio_static/", import.meta.url);
await mkdir(output, { recursive: true });
await build({
  entryPoints: ["src/main.tsx"], bundle: true, minify: true, sourcemap: false,
  outfile: new URL("app.js", output).pathname,
  target: ["chrome120", "firefox121", "safari17"], jsx: "automatic",
  define: { "process.env.NODE_ENV": '"production"' },
  legalComments: "eof",
});
await copyFile(new URL("index.html", import.meta.url), new URL("index.html", output));
console.log("Studio built into exposlides/studio_static");
