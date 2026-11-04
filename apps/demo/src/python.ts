export type TestRun = { passed: boolean; output: string };

const LIMIT_MS = 60_000; // first run downloads Python, so be generous
let worker: Worker | null = null;
let next = 0;

function start(): Worker {
  worker ??= new Worker(new URL("./pyWorker.ts", import.meta.url), { type: "module" });
  return worker;
}

/** Real pytest, in the visitor's browser. A run that hangs is stopped and the worker restarted. */
export function runTests(files: Record<string, string>): Promise<TestRun> {
  const w = start();
  const id = ++next;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      w.terminate();
      worker = null;
      resolve({ passed: false, output: "The tests took too long and were stopped." });
    }, LIMIT_MS);
    const onMessage = (e: MessageEvent) => {
      if (e.data.id !== id) return;
      clearTimeout(timer);
      w.removeEventListener("message", onMessage);
      if (e.data.ok) resolve({ passed: e.data.code === 0, output: e.data.output });
      else {
        resolve({
          passed: false,
          output: `Python could not start here (${e.data.error}). Check your connection and try again.`,
        });
      }
    };
    w.addEventListener("message", onMessage);
    w.postMessage({ id, files });
  });
}
