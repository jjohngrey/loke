"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { LearningView } from "@loke/contracts";

function Icon({ name }: { name: string }) {
  const paths: Record<string, React.ReactNode> = {
    today: (
      <>
        <rect x="4" y="5" width="16" height="15" rx="3" />
        <path d="M8 3v4m8-4v4M4 10h16m-11 5h6" />
      </>
    ),
    study: (
      <>
        <path d="M4 5h6a3 3 0 0 1 3 3v12a4 4 0 0 0-4-3H4zm16 0h-4a3 3 0 0 0-3 3v12a4 4 0 0 1 4-3h3z" />
      </>
    ),
    concepts: (
      <>
        <circle cx="6" cy="7" r="3" />
        <circle cx="18" cy="8" r="3" />
        <circle cx="12" cy="18" r="3" />
        <path d="m8 9 2 6m5-4-2 4M9 7h6" />
      </>
    ),
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    mic: (
      <>
        <rect x="9" y="3" width="6" height="12" rx="3" />
        <path d="M6 10v2a6 6 0 0 0 12 0v-2m-6 8v3m-4 0h8" />
      </>
    ),
    attach: (
      <path d="m9 17 8-8a3 3 0 0 0-4-4L5 13a5 5 0 0 0 7 7l8-8M8 14l6-6" />
    ),
    check: <path d="m5 12 4 4 10-10" />,
  };
  return (
    <svg
      aria-hidden="true"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name] || paths.arrow}
    </svg>
  );
}

async function api<T>(
  path: string,
  body?: unknown,
  method = body ? "POST" : "GET",
): Promise<T> {
  const response = await fetch(`/api/backend/${path}`, {
    method,
    headers: body ? { "content-type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(result.detail || "The learning request failed.");
  return result;
}

export default function Workspace() {
  const [view, setView] = useState<LearningView | null>(null);
  const latest = useRef<LearningView | null>(null);
  const [tab, setTab] = useState("Today");
  const [goal, setGoal] = useState(
    "Understand how neurons release neurotransmitters",
  );
  const [consent, setConsent] = useState(false);
  const [audioConsent, setAudioConsent] = useState(false);
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"text" | "voice" | "attachment">("text");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recording, setRecording] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const update = useCallback((next: LearningView) => {
    const old = latest.current;
    if (
      old &&
      (next.state_revision < old.state_revision ||
        next.plan_revision < old.plan_revision)
    )
      return;
    latest.current = next;
    setView(next);
  }, []);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const data = await api<LearningView>("view");
        if (active) update(data);
      } catch (e) {
        if (active && !latest.current) setError((e as Error).message);
      }
    };
    load();
    const timer = setInterval(load, 2000);
    return () => {
      active = false;
      clearInterval(timer);
      if (timerRef.current) clearTimeout(timerRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, [update]);
  useEffect(() => {
    setAnswer("");
  }, [view?.active_quiz?.id]);
  async function act(path: string, body?: unknown, method?: string) {
    setBusy(true);
    setError("");
    try {
      const next = await api<LearningView>(path, body, method);
      update(next);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function submitReport(event: React.FormEvent) {
    event.preventDefault();
    if (await act("input", { request_id: crypto.randomUUID(), text, mode })) {
      setText("");
      setMode("text");
    }
  }
  async function transcribe(blob: Blob, filename: string) {
    setBusy(true);
    setError("");
    try {
      const data = new FormData();
      data.append("file", blob, filename);
      const response = await fetch("/api/backend/audio/transcribe", {
        method: "POST",
        headers: { "audio-consent": "true" },
        body: data,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail);
      setText(result.text);
      setMode("voice");
      setTab("Study");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function toggleRecording() {
    if (recording) {
      recorder.current?.stop();
      return;
    }
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const instance = new MediaRecorder(stream);
      recorder.current = instance;
      const chunks: Blob[] = [];
      instance.ondataavailable = (event) => chunks.push(event.data);
      instance.onstop = () => {
        if (timerRef.current) clearTimeout(timerRef.current);
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const blob = new Blob(chunks, { type: instance.mimeType });
        const extension = instance.mimeType.includes("mp4") ? "m4a" : "webm";
        transcribe(blob, `recording.${extension}`);
      };
      instance.start();
      setRecording(true);
      timerRef.current = setTimeout(() => instance.stop(), 30000);
    } catch {
      setError(
        "Microphone access was unavailable. You can type your study report instead.",
      );
    }
  }
  async function attachment(file?: File) {
    if (!file) return;
    if (file.size > 1_000_000) {
      setError("Use an attachment under 1 MB.");
      return;
    }
    if (/\.(md|txt)$/i.test(file.name)) {
      const content = await file.text();
      if (content.length > 15000) {
        setError("Use a note under 15,000 characters.");
        return;
      }
      setText(content);
      setMode("attachment");
      setTab("Study");
    } else if (/\.(mp3|mp4|m4a|wav|webm)$/i.test(file.name)) {
      if (!audioConsent) {
        setError("Enable audio processing before attaching audio.");
        return;
      }
      await transcribe(file, file.name);
    } else
      setError(
        "Supported attachments: Markdown, text, MP3, MP4, M4A, WAV or WebM.",
      );
  }
  const concept = (id: string) => view?.concepts.find((c) => c.id === id);
  const quiz = view?.active_quiz;
  const stateLabel: Record<string, string> = {
    needs_practice: "Needs practice",
    recent_unassisted_correct: "One recent correct item",
    attempted: "Attempted",
    unassessed: "Not checked",
  };

  return (
    <div className="shell">
      <aside className="sidebar">
        <a href="/" className="brand" aria-label="Loke home">
          <span className="brand-mark">l</span>
          <span>loke</span>
        </a>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <nav aria-label="Learning workspace">
          {["Today", "Study", "Concepts"].map((name) => (
            <button
              key={name}
              className={`nav-item ${tab === name ? "selected" : ""}`}
              onClick={() => setTab(name)}
              aria-current={tab === name ? "page" : undefined}
            >
              <Icon name={name.toLowerCase()} />
              {name}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-dot" />
          <span>Personal learning space</span>
          <p>
            {view?.agent_id
              ? "Your history stays connected."
              : "One goal. A clear next step."}
          </p>
        </div>
      </aside>
      <main className="main" aria-busy={busy}>
        <header className="topbar">
          <span>
            Neuroscience <span className="breadcrumb">/</span> {tab}
          </span>
          <span className="mode-badge">
            {view?.model_mode === "live" ? "Live explanations" : "Demo mode"}
          </span>
        </header>
        <div className="page-heading">
          <div className="eyebrow">A LITTLE MORE UNDERSTANDING</div>
          <h1>
            {tab === "Concepts"
              ? "See the connections."
              : tab === "Study"
                ? "Make sense of what you studied."
                : "Your next step, thoughtfully chosen."}
          </h1>
          <p>Neural signaling, one useful connection at a time.</p>
        </div>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <div className="workspace-grid">
          <div className="primary">
            {!view?.storage_consent ? (
              <section className="card goal-card">
                <div className="card-kicker">START WITH A GOAL</div>
                <h2>What would you like to understand?</h2>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    act("goal", {
                      request_id: crypto.randomUUID(),
                      goal,
                      storage_consent: consent,
                      reminders_enabled: true,
                      study_minutes: 10,
                    });
                  }}
                >
                  <label htmlFor="goal">Your learning goal</label>
                  <textarea
                    id="goal"
                    value={goal}
                    onChange={(e) => setGoal(e.target.value)}
                    required
                    minLength={3}
                    maxLength={500}
                  />
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={consent}
                      onChange={(e) => setConsent(e.target.checked)}
                    />
                    Save my goal, notes and answers for this seven-day demo.
                  </label>
                  <p className="helper">
                    You can turn reminders off or delete your history at any
                    time.
                  </p>
                  <button
                    className="primary-button"
                    disabled={busy || !consent}
                  >
                    {busy ? "Creating your plan…" : "Create my study plan"}
                    <Icon name="arrow" />
                  </button>
                </form>
              </section>
            ) : (
              <>
                <section className="goal-summary">
                  <span className="card-kicker">YOUR GOAL</span>
                  <h2>{view.goal}</h2>
                  <span className="small">
                    A short plan · About{" "}
                    {view.plan.reduce(
                      (total, activity) => total + (activity.minutes ?? 2),
                      0,
                    )}{" "}
                    minutes
                  </span>
                </section>
                {tab === "Concepts" ? (
                  <section className="card">
                    <div className="card-kicker">CONNECTED KNOWLEDGE</div>
                    <h2>A small map of neural signaling</h2>
                    <p className="helper">
                      Links describe teaching prerequisites. They do not measure
                      what you know.
                    </p>
                    <div className="concept-list">
                      {view.concepts.map((c) => (
                        <article key={c.id}>
                          <h3>{c.label}</h3>
                          <span className="state-label">
                            {
                              stateLabel[
                                view.states.find((s) => s.concept_id === c.id)
                                  ?.status || "unassessed"
                              ]
                            }
                          </span>
                          <p>
                            {c.prerequisites.length
                              ? `Builds on ${c.prerequisites.map((id) => concept(id)?.label).join(", ")}.`
                              : "A foundational concept."}
                          </p>
                          <a
                            href={c.resource_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Read the textbook chapter ↗
                          </a>
                        </article>
                      ))}
                    </div>
                  </section>
                ) : (
                  <>
                    <section className="card plan-card">
                      <div className="card-top">
                        <div>
                          <div className="card-kicker">YOUR STUDY PLAN</div>
                          <h2>A useful sequence</h2>
                        </div>
                        <span className="pill">Adapts with your answers</span>
                      </div>
                      <ol className="plan-list">
                        {view.plan.map((activity, i) => (
                          <li
                            key={activity.concept_id}
                            className={i === 0 ? "current" : ""}
                          >
                            <span className="step-number">{i + 1}</span>
                            <div>
                              <h3>{activity.title}</h3>
                              <p>
                                {activity.kind === "diagnostic"
                                  ? "A quick check"
                                  : activity.kind === "review"
                                    ? "Scheduled review"
                                    : activity.kind === "practice"
                                      ? "Practice again"
                                      : "Make the connection"}{" "}
                                · {activity.minutes} min
                              </p>
                            </div>
                            {i === 0 && (
                              <span className="next-pill">Up next</span>
                            )}
                          </li>
                        ))}
                      </ol>
                    </section>
                    {view.notifications.length > 0 && (
                      <section
                        className="reminder"
                        aria-label="Review reminders"
                      >
                        <div className="reminder-icon">
                          <Icon name="today" />
                        </div>
                        <div>
                          <h3>{view.notifications.at(-1)?.title}</h3>
                          <p>
                            A review is scheduled from your recorded answer.
                          </p>
                        </div>
                      </section>
                    )}
                    <section className="card quiz-card">
                      <div className="card-kicker">
                        ONE QUESTION, STRONGER EVIDENCE
                      </div>
                      <h2>
                        {quiz?.prompt || "Your next question will appear here."}
                      </h2>
                      {quiz && (
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            act("quiz/answer", {
                              request_id: crypto.randomUUID(),
                              card_id: quiz.id,
                              answer,
                            });
                          }}
                        >
                          {quiz.kind === "mcq" ? (
                            <fieldset>
                              <legend className="sr-only">
                                Choose one answer
                              </legend>
                              {Object.entries(quiz.options || {}).map(
                                ([key, label]) => (
                                  <label
                                    key={key}
                                    className={`option ${answer === key ? "option-selected" : ""}`}
                                  >
                                    <input
                                      type="radio"
                                      name="answer"
                                      value={key}
                                      checked={answer === key}
                                      onChange={() => setAnswer(key)}
                                    />
                                    <span className="option-letter">{key}</span>
                                    <span>{label}</span>
                                  </label>
                                ),
                              )}
                            </fieldset>
                          ) : (
                            <>
                              <label htmlFor="blank-answer">
                                Your short answer
                              </label>
                              <input
                                id="blank-answer"
                                className="text-input"
                                value={answer}
                                onChange={(e) => setAnswer(e.target.value)}
                                placeholder="For example: K+"
                                autoComplete="off"
                                required
                              />
                            </>
                          )}
                          <button
                            className="primary-button"
                            disabled={busy || !answer.trim()}
                          >
                            Check my answer
                            <Icon name="arrow" />
                          </button>
                        </form>
                      )}
                      <div className="feedback" role="status">
                        {view.response}
                      </div>
                    </section>
                    <section className="card report-card">
                      <div className="card-kicker">
                        CAPTURE WHAT YOU STUDIED
                      </div>
                      <h2>Bring your thoughts into the picture.</h2>
                      <form onSubmit={submitReport}>
                        <label htmlFor="study-report">
                          Study report or question
                        </label>
                        <textarea
                          id="study-report"
                          placeholder="I studied action potentials, but I'm still unsure about…"
                          value={text}
                          onChange={(e) => setText(e.target.value)}
                          maxLength={15000}
                          required
                        />
                        {mode !== "text" && (
                          <p className="helper">
                            {mode === "voice"
                              ? "Review and edit the transcript before sending."
                              : "Review your attached note before sending."}
                          </p>
                        )}
                        <div className="report-actions">
                          <button
                            type="button"
                            className={`quiet-button ${recording ? "recording" : ""}`}
                            onClick={toggleRecording}
                            disabled={busy || !audioConsent}
                            aria-pressed={recording}
                          >
                            <Icon name="mic" />
                            {recording ? "Stop recording" : "Record"}
                          </button>
                          <button
                            type="button"
                            className="quiet-button"
                            onClick={() => fileRef.current?.click()}
                            disabled={busy}
                          >
                            <Icon name="attach" />
                            Attach
                          </button>
                          <button
                            className="primary-button"
                            disabled={busy || !text.trim()}
                          >
                            Send report
                            <Icon name="arrow" />
                          </button>
                        </div>
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={audioConsent}
                            onChange={(e) => setAudioConsent(e.target.checked)}
                          />
                          Allow audio to be sent to OpenAI for transcription.
                          Original audio is not stored.
                        </label>
                        <p className="helper">
                          Recordings stop at 30 seconds. Review the transcript
                          before it becomes learning history.
                        </p>
                      </form>
                      <input
                        className="sr-only"
                        ref={fileRef}
                        type="file"
                        aria-label="Attach study note or audio"
                        accept=".txt,.md,.mp3,.mp4,.m4a,.wav,.webm"
                        onChange={(e) => {
                          attachment(e.target.files?.[0]);
                          e.target.value = "";
                        }}
                      />
                    </section>
                  </>
                )}
              </>
            )}
          </div>
          <aside className="details-column" aria-label="Learning context">
            <section className="card why-card">
              <div className="detail-icon">
                <Icon name="concepts" />
              </div>
              <h2>Why this next?</h2>
              <p>
                {view?.plan[0]?.reason ||
                  "Your goal sets the direction. A short check helps choose a useful place to begin."}
              </p>
              <div className="evidence-chip">
                <span className="status-dot" />
                {view?.plan[0]?.reason_event_ids.length
                  ? "Grounded in a recorded answer"
                  : "A check, not a mastery claim"}
              </div>
            </section>
            <section className="card diagram-card">
              <div className="card-kicker">THE BIG PICTURE</div>
              <h2>A connected sequence</h2>
              <svg
                viewBox="0 0 240 205"
                role="img"
                aria-labelledby="diagram-title"
              >
                <title id="diagram-title">
                  Ionic gradients support action potentials, which lead to
                  calcium entry and transmitter release.
                </title>
                {[
                  "Ionic gradients",
                  "Action potentials",
                  "Calcium entry",
                  "Transmitter release",
                ].map((label, i) => (
                  <g key={label}>
                    <rect
                      x="14"
                      y={10 + i * 49}
                      width="212"
                      height="36"
                      rx="9"
                      fill={i === 1 ? "#EAF2FF" : "#F5F5F7"}
                      stroke={i === 1 ? "#D2E2FB" : "#E8E8ED"}
                    />
                    <text
                      x="120"
                      y={33 + i * 49}
                      textAnchor="middle"
                      fill="#344054"
                      fontSize="12"
                    >
                      {label}
                    </text>
                    {i < 3 && (
                      <path
                        d={`M120 ${46 + i * 49}v12m-3-3 3 3 3-3`}
                        fill="none"
                        stroke="#A1A6B0"
                      />
                    )}
                  </g>
                ))}
              </svg>
              <p className="helper">
                A reviewed teaching sequence, not a learner score.
              </p>
            </section>
            <section className="card">
              <div className="card-kicker">EXPLORE A LITTLE FURTHER</div>
              <h2>From the textbook</h2>
              <a
                className="resource-link"
                href="https://nba.uth.tmc.edu/neuroscience/m/s1/chapter02.html"
                target="_blank"
                rel="noreferrer"
              >
                <span>Ionic mechanisms & action potentials</span>
                <span>↗</span>
              </a>
              {view?.sources.map((source) => (
                <blockquote key={source.source_id}>
                  <strong>{source.title}</strong>
                  <p>{source.text.slice(0, 200)}</p>
                </blockquote>
              ))}
            </section>
            {view?.storage_consent && (
              <section className="card settings-card">
                <h2>Your learning history</h2>
                <p>
                  {view.events.length} recent events saved. Reports and item
                  evidence remain distinct.
                </p>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={view.reminders_enabled}
                    onChange={(e) =>
                      act("reminders", { enabled: e.target.checked })
                    }
                    disabled={busy}
                  />
                  In-app review reminders
                </label>
                <details>
                  <summary>Demo controls</summary>
                  <p className="helper">
                    This visibly advances the test clock. It does not prove
                    forgetting.
                  </p>
                  <button
                    className="quiet-button"
                    disabled={busy}
                    onClick={() => act("demo/clock", { hours: 24 })}
                  >
                    Advance review clock +24h
                  </button>
                  <p className="small">
                    Demo clock: +{view.demo_clock_hours} hours
                  </p>
                </details>
                <button
                  className="delete-button"
                  disabled={busy}
                  onClick={async () => {
                    if (
                      !confirm(
                        "Delete this demo learner’s goal, notes, answers and reminders?",
                      )
                    )
                      return;
                    setBusy(true);
                    try {
                      const next = await api<LearningView>(
                        "learner",
                        undefined,
                        "DELETE",
                      );
                      latest.current = null;
                      update(next);
                      setConsent(false);
                      setText("");
                    } catch (e) {
                      setError((e as Error).message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Delete learning data
                </button>
              </section>
            )}
          </aside>
        </div>
        <footer className="footer">
          <span>Small steps. Connected understanding.</span>
          <span role="status">
            {recording
              ? "Recording audio…"
              : busy
                ? "Saving your learning turn…"
                : view?.agent_id
                  ? "Learning history connected"
                  : "Ready when you are"}
          </span>
        </footer>
      </main>
    </div>
  );
}
