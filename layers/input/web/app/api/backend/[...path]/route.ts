// Adapted from OpenPoke web/app/api/chat/route.ts (MIT).
// Copyright (c) 2025 OpenPoke Contributors. See third_party/openpoke/LICENSE.
// Changes: allowlisted learning routes, authenticated proxy, multipart forwarding and no public keys.
export const runtime = "nodejs";
const allowed = new Set([
  "view",
  "capabilities",
  "workspace",
  "workspace/folder",
  "workspace/chat",
  "chats/history",
  "attachments/preview",
  "goal",
  "input",
  "quiz/answer",
  "reminders",
  "demo/clock",
  "learner",
  "audio/transcribe",
  "runtime/run",
  "runtime/cancel",
  "runtime/reset",
]);
async function proxy(
  req: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const origin = req.headers.get("origin");
  if (origin) {
    try {
      const source = new URL(origin);
      const target = new URL(req.url);
      if (
        source.protocol !== "http:" ||
        !["127.0.0.1", "localhost"].includes(source.hostname) ||
        source.port !== target.port
      )
        return Response.json(
          { detail: "Unsupported origin." },
          { status: 403 },
        );
    } catch {
      return Response.json({ detail: "Unsupported origin." }, { status: 403 });
    }
  }
  const { path } = await context.params;
  const route = path.join("/");
  const query = new URL(req.url).search;
  if (!allowed.has(route))
    return Response.json({ detail: "Unknown route." }, { status: 404 });
  const headers = new Headers({
    "x-loke-session": process.env.SESSION_TOKEN || "local-demo-change-me",
  });
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const generation = req.headers.get("generation-id");
  if (generation) headers.set("generation-id", generation);
  if (req.headers.get("audio-consent") === "true")
    headers.set("audio-consent", "true");
  let body: Uint8Array | undefined;
  if (!["GET", "HEAD"].includes(req.method) && req.body) {
    const reader = req.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 5_100_000) {
        await reader.cancel();
        return Response.json(
          { detail: "Upload exceeds the 5 MB file limit." },
          { status: 413 },
        );
      }
      chunks.push(value);
    }
    body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      body.set(chunk, offset);
      offset += chunk.byteLength;
    }
  }
  try {
    const upstream = await fetch(
      `${process.env.BACKEND_URL || "http://127.0.0.1:8000"}/api/${route}${query}`,
      {
        method: req.method,
        headers,
        body: body as BodyInit | undefined,
        cache: "no-store",
        signal: AbortSignal.any([req.signal, AbortSignal.timeout(35000)]),
      },
    );
    const streaming = upstream.headers
      .get("content-type")
      ?.startsWith("application/x-ndjson");
    return new Response(
      streaming ? upstream.body : await upstream.arrayBuffer(),
      {
        status: upstream.status,
        headers: {
          "content-type":
            upstream.headers.get("content-type") || "application/json",
          "cache-control": "no-store",
          ...(streaming ? { "x-accel-buffering": "no" } : {}),
        },
      },
    );
  } catch {
    return Response.json(
      {
        detail: "Learning service is unavailable. Check the backend and retry.",
      },
      { status: 502 },
    );
  }
}
export { proxy as GET, proxy as POST, proxy as DELETE };
