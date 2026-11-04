/// <reference lib="webworker" />
// Runs the learner's tests with real pytest inside Python compiled to WebAssembly (Pyodide).
// It lives in a worker so a slow or looping test cannot freeze the page, and can be stopped.

const CDN = "https://cdn.jsdelivr.net/pyodide/v0.28.0/full/";

type Py = {
  loadPackage(name: string): Promise<void>;
  runPython(code: string): string;
  FS: { mkdirTree(path: string): void; writeFile(path: string, text: string): void };
};

let loaded: Promise<Py> | null = null;
let runs = 0;

function pyodide(): Promise<Py> {
  loaded ??= (async () => {
    const mod = (await import(/* @vite-ignore */ `${CDN}pyodide.mjs`)) as {
      loadPyodide(o: { indexURL: string }): Promise<Py>;
    };
    const py = await mod.loadPyodide({ indexURL: CDN });
    await py.loadPackage("pytest");
    return py;
  })();
  return loaded;
}

const RUN = (root: string) => `
import contextlib, io, os, sys
os.chdir("${root}")
sys.path.insert(0, "${root}")
for name in [k for k, v in list(sys.modules.items())
             if str(getattr(v, "__file__", "") or "").startswith("/w")]:
    del sys.modules[name]
import pytest
buffer = io.StringIO()
with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
    code = pytest.main(["-q", "--tb=short", "-p", "no:cacheprovider", "-p", "no:faulthandler"])
sys.path.remove("${root}")
str(int(code)) + "\\n" + buffer.getvalue()
`;

self.onmessage = async (event: MessageEvent<{ id: number; files: Record<string, string> }>) => {
  const { id, files } = event.data;
  try {
    const py = await pyodide();
    const root = `/w${++runs}`;
    for (const [path, text] of Object.entries(files)) {
      const target = `${root}/${path}`;
      py.FS.mkdirTree(target.split("/").slice(0, -1).join("/"));
      py.FS.writeFile(target, text);
    }
    const out = py.runPython(RUN(root));
    const cut = out.indexOf("\n");
    self.postMessage({ id, ok: true, code: Number(out.slice(0, cut)), output: out.slice(cut + 1) });
  } catch (error) {
    self.postMessage({ id, ok: false, error: String(error) });
  }
};
