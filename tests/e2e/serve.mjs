// Serves web/ with the headers of web/_headers, API_ORIGIN replaced by the API it should talk to.
//   node tests/e2e/serve.mjs [port] [api origin]      (npm run serve)
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(fileURLToPath(new URL(".", import.meta.url)), "../../web");
const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css" };

export function serveWeb(port, apiOrigin) {
  const policy = Object.fromEntries(
    readFileSync(join(root, "_headers"), "utf8")
      .split("\n").slice(1)
      .map((line) => line.trim().split(/: (.*)/s).slice(0, 2))
      .filter(([name]) => name)
      .map(([name, value]) => [name, value.replace("API_ORIGIN", apiOrigin)]),
  );
  const server = createServer((req, res) => {
    const path = normalize(new URL(req.url, "http://x").pathname).replace(/^(\.\.[/\\])+/, "");
    const file = join(root, path === "/" ? "index.html" : path);
    if (path === "/config.js") {  // production's config.js points at the deployed API
      res.writeHead(200, { ...policy, "Content-Type": types[".js"] }).end(`window.API_BASE = ${JSON.stringify(apiOrigin)};`);
      return;
    }
    if (!file.startsWith(root) || !existsSync(file) || file.endsWith("_headers")) {
      res.writeHead(404, policy).end("not found");
      return;
    }
    res.writeHead(200, { ...policy, "Content-Type": types[extname(file)] ?? "application/octet-stream" });
    res.end(readFileSync(file));
  });
  return new Promise((resolve) => server.listen(port, () => resolve(server)));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [port = 8080, api = "http://localhost:8000"] = process.argv.slice(2);
  await serveWeb(Number(port), api);
  console.log(`web on http://localhost:${port}, api ${api}`);
}
