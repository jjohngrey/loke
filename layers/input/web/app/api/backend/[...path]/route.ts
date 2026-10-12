// Adapted from OpenPoke web/app/api/chat/route.ts (MIT).
// Copyright (c) 2025 OpenPoke Contributors. See third_party/openpoke/LICENSE.
// Changes: allowlisted learning routes, authenticated proxy, multipart forwarding and no public keys.
export const runtime = "nodejs";
const allowed = new Set([
  "view",
  "goal",
  "input",
  "quiz/answer",
  "reminders",
  "demo/clock",
  "learner",
  "audio/transcribe",
]);
async function proxy(
  req: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const origin = req.headers.get("origin");
  if (
    origin &&
    !["http://127.0.0.1:3000", "http://localhost:3000"].includes(origin)
  )
    return Response.json({ detail: "Unsupported origin." }, { status: 403 });
  const { path } = await context.params;
  const route = path.join("/");
  if (!allowed.has(route))
    return Response.json({ detail: "Unknown route." }, { status: 404 });
  const headers = new Headers({
    "x-loke-session": process.env.SESSION_TOKEN || "local-demo-change-me",
  });
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  if (req.headers.get("audio-consent") === "true")
    headers.set("audio-consent", "true");
  try {
    const upstream = await fetch(
      `${process.env.BACKEND_URL || "http://127.0.0.1:8000"}/api/${route}`,
      {
        method: req.method,
        headers,
        body: ["GET", "HEAD"].includes(req.method)
          ? undefined
          : await req.arrayBuffer(),
        cache: "no-store",
        signal: AbortSignal.timeout(35000),
      },
    );
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") || "application/json",
        "cache-control": "no-store",
      },
    });
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
