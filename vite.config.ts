import { defineConfig, PluginOption } from "vite";
import react from "@vitejs/plugin-react";

function routeAliasPlugin() {
  const rewriteMap = new Map([
    ["/debug", "/debug.html"],
    ["/preview", "/preview.html"],
  ]);

  const rewrite = (url: string | undefined): string | undefined => {
    if (!url) return url;
    const [path, search = ""] = url.split("?");
    const target = rewriteMap.get(path);
    if (!target) return url;
    return `${target}${search ? `?${search}` : ""}`;
  };

  return {
    name: "route-alias-plugin",
    configureServer(server: { middlewares: { use: (fn: (req: { url?: string }, _res: unknown, next: () => void) => void) => void } }) {
      server.middlewares.use((req, _res, next) => {
        req.url = rewrite(req.url);
        next();
      });
    },
    configurePreviewServer(server: { middlewares: { use: (fn: (req: { url?: string }, _res: unknown, next: () => void) => void) => void } }) {
      server.middlewares.use((req, _res, next) => {
        req.url = rewrite(req.url);
        next();
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const includeAuxPages = mode === "development";

  let input: Record<string, string> = { main: "index.html", notFound: "404.html" };
  let plugins: PluginOption[] = [react()];

  if (includeAuxPages) {
    input = {
      ...input,
      debug: "debug.html",
      preview: "preview.html",
    };
    plugins = [...plugins, routeAliasPlugin()]
  }

  return {
    plugins,
    build: {
      rollupOptions: {
        input
      },
    },
    test: {
      environment: "node",
      include: ["src/**/*.test.{ts,tsx}"],
    },
  };
});
