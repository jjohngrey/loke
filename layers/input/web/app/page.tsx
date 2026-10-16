"use client";

import dynamic from "next/dynamic";
import { useWorkspace } from "./use-workspace";
import { useMediaInput } from "./use-media-input";
import type { Chat } from "./use-workspace";
import type { LearningInput } from "@loke/contracts";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

const Seasons = dynamic(() => import("anatomy-figures/seasons"), {
  ssr: false,
});

function SeasonsEmptyState() {
  const figureRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = figureRef.current;
    if (!container) return;

    const sheet = new CSSStyleSheet();
    sheet.replaceSync(
      '[data-corner="title"], [data-corner="hint"] { display: none; }',
    );
    let shadowRoot: ShadowRoot | null = null;
    let frame = 0;

    const attachSheet = () => {
      frame = 0;
      const nextRoot = container.querySelector(
        "[data-anatomy-figure]",
      )?.shadowRoot;
      if (!nextRoot) {
        frame = requestAnimationFrame(attachSheet);
        return;
      }
      if (nextRoot === shadowRoot) return;
      if (shadowRoot) {
        shadowRoot.adoptedStyleSheets = shadowRoot.adoptedStyleSheets.filter(
          (item) => item !== sheet,
        );
      }
      nextRoot.adoptedStyleSheets = [...nextRoot.adoptedStyleSheets, sheet];
      shadowRoot = nextRoot;
    };

    const observer = new MutationObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(attachSheet);
    });
    observer.observe(container, { childList: true, subtree: true });
    attachSheet();

    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      if (shadowRoot) {
        shadowRoot.adoptedStyleSheets = shadowRoot.adoptedStyleSheets.filter(
          (item) => item !== sheet,
        );
      }
    };
  }, []);

  return (
    <section className="seasons-empty" aria-labelledby="seasons-question">
      <h1 className="sr-only" id="seasons-question">
        Explore why Earth has seasons
      </h1>
      <div className="seasons-figure" ref={figureRef}>
        <Seasons theme="light" fig="" />
      </div>
    </section>
  );
}

type IconName =
  | "sidebar"
  | "compose"
  | "search"
  | "folder"
  | "chevron"
  | "home"
  | "book"
  | "clock"
  | "plus"
  | "mic"
  | "voice"
  | "send"
  | "settings"
  | "logout"
  | "close"
  | "spark"
  | "check";

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    sidebar: (
      <>
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M9 4v16" />
      </>
    ),
    compose: (
      <>
        <path d="M12 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7" />
        <path d="m16 4 4 4-9 9-4 1 1-4z" />
      </>
    ),
    search: (
      <>
        <circle cx="10.8" cy="10.8" r="6.8" />
        <path d="m16 16 4.5 4.5" />
      </>
    ),
    folder: (
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    ),
    chevron: <path d="m9 6 6 6-6 6" />,
    home: (
      <>
        <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" />
        <path d="M9 21v-7h6v7" />
      </>
    ),
    book: (
      <>
        <path d="M4 4.5h6a3 3 0 0 1 3 3V20a4 4 0 0 0-4-3H4z" />
        <path d="M20 4.5h-4a3 3 0 0 0-3 3V20a4 4 0 0 1 4-3h3z" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    plus: <path d="M12 4v16M4 12h16" />,
    mic: (
      <>
        <rect x="9" y="3" width="6" height="12" rx="3" />
        <path d="M6 10v2a6 6 0 0 0 12 0v-2m-6 8v3m-4 0h8" />
      </>
    ),
    voice: <path d="M5 10v4m4-7v10m4-13v16m4-10v4" />,
    send: <path d="M12 19V5m-6 6 6-6 6 6" />,
    settings: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l-1.7 1.7a1.6 1.6 0 0 0-1.8-.3 8 8 0 0 1-1.4.6L14.2 21h-2.4l-.6-2.2a8 8 0 0 1-1.4-.6 1.6 1.6 0 0 0-1.8.3l-1.7-1.7a1.6 1.6 0 0 0 .3-1.8 8 8 0 0 1-.6-1.4L3.8 13v-2.4L6 10a8 8 0 0 1 .6-1.4 1.6 1.6 0 0 0-.3-1.8L8 5.1a1.6 1.6 0 0 0 1.8.3 8 8 0 0 1 1.4-.6l.6-2.2h2.4l.6 2.2a8 8 0 0 1 1.4.6 1.6 1.6 0 0 0 1.8-.3l1.7 1.7a1.6 1.6 0 0 0-.3 1.8 8 8 0 0 1 .6 1.4l2.2.6V13l-2.2.6a8 8 0 0 1-.6 1.4z" />
      </>
    ),
    logout: (
      <>
        <path d="M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4" />
        <path d="M13 8l4 4-4 4m4-4H8" />
      </>
    ),
    close: <path d="M5 5l14 14M19 5 5 19" />,
    spark: (
      <>
        <path d="m12 2 1.9 7.1L21 11l-7.1 1.9L12 20l-1.9-7.1L3 11l7.1-1.9z" />
        <path d="m19 17 .6 2.4L22 20l-2.4.6L19 23l-.6-2.4L16 20l2.4-.6z" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
  };
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  );
}

type Section = "chats" | "study" | "activity";

const railItems: { id: Section; label: string; icon: IconName }[] = [
  { id: "chats", label: "Chats", icon: "home" },
  { id: "study", label: "Study", icon: "book" },
  { id: "activity", label: "Activity", icon: "clock" },
];

export default function Workspace() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [section, setSection] = useState<Section>("chats");

  const [expandedFolders, setExpandedFolders] = useState<
    Record<string, boolean>
  >({});
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [addingFolder, setAddingFolder] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const [dialog, setDialog] = useState<"settings" | "logout" | null>(null);
  const profileName = "Learner";
  const [goal, setGoal] = useState("Understand neural signaling");
  const [storageConsent, setStorageConsent] = useState(false);
  const [inputMode, setInputMode] = useState<LearningInput["mode"]>("text");
  const [inputLabel, setInputLabel] = useState("");
  const [answer, setAnswer] = useState("");
  const [speak, setSpeak] = useState(false);
  const workspace = useWorkspace(activeChatId, () => {
    setActiveChatId(null);
    setDraft("");
    setInputLabel("");
    setInputMode("text");
    window.speechSynthesis?.cancel();
  });
  const { chats, folders, view, busy, error } = workspace;
  const media = useMediaInput(
    view?.generation_id,
    !!view?.storage_consent,
    (text, mode, label) => {
      setDraft(text);
      setInputMode(mode);
      setInputLabel(label);
      composerRef.current?.focus();
    },
  );
  const dialogRef = useRef<HTMLDivElement>(null);
  const savedFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!dialog) return;
    savedFocus.current = document.activeElement as HTMLElement;
    const box = dialogRef.current;
    box?.querySelector<HTMLElement>("button, input")?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !box) return;
      const items = [
        ...box.querySelectorAll<HTMLElement>(
          "button:not(:disabled), input, a[href]",
        ),
      ];
      const first = items[0],
        last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    box?.addEventListener("keydown", trap);
    return () => {
      box?.removeEventListener("keydown", trap);
      savedFocus.current?.focus();
    };
  }, [dialog]);
  useEffect(() => {
    setAnswer("");
  }, [view?.active_quiz?.id, view?.state_revision]);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeChat = chats.find((chat) => chat.id === activeChatId);
  const matches = (chat: Chat) =>
    (chat.title + " " + chat.messages.map((m) => m.text).join(" "))
      .toLowerCase()
      .includes(search.trim().toLowerCase());
  const recent = chats.filter((chat) => !chat.folderId && matches(chat));

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
        event.preventDefault();
        setSidebarOpen((open) => !open);
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
        setSidebarOpen(true);
      }
      if (event.key === "Escape") {
        setProfileOpen(false);
        setDialog(null);
        setSearchOpen(false);
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (
        profileRef.current &&
        !profileRef.current.contains(event.target as Node)
      )
        setProfileOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: "end" });
  }, [activeChatId, chats]);

  function selectChat(id: string) {
    setSection("chats");
    setActiveChatId(id);
    media.cancel();
    setDraft("");
    setInputMode("text");
    setInputLabel("");
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.trim() || busy || media.state !== "idle") return;
    const id = activeChatId || crypto.randomUUID();
    const text = draft.trim();
    try {
      if (await workspace.send(id, text, inputMode, inputLabel)) {
        setActiveChatId(id);
        setDraft("");
        setInputLabel("");
        setInputMode("text");
        if (speak && window.speechSynthesis) {
          window.speechSynthesis.speak(
            new SpeechSynthesisUtterance(workspace.reply()),
          );
        }
      }
    } catch (e) {
      workspace.setError((e as Error).message);
    }
  }

  async function addFolder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = folderName.trim();
    if (!name) return;
    try {
      if (await workspace.addFolder(name)) {
        setFolderName("");
        setAddingFolder(false);
      }
    } catch (e) {
      workspace.setError((e as Error).message);
    }
  }

  function chatButton(chat: Chat, nested = false) {
    const selected = activeChatId === chat.id && section === "chats";
    return (
      <button
        key={chat.id}
        className={[
          "chat-item",
          nested ? "nested" : "",
          selected ? "selected" : "",
        ].join(" ")}
        onClick={() => selectChat(chat.id)}
        title={chat.title}
        disabled={busy || media.state !== "idle"}
        aria-current={selected ? "page" : undefined}
      >
        <span>{chat.title}</span>
      </button>
    );
  }

  return (
    <div
      className={[
        "desktop-shell",
        sidebarOpen ? "sidebar-open" : "sidebar-closed",
      ].join(" ")}
    >
      <header className="window-bar">
        <button
          className="window-sidebar-toggle icon-button"
          onClick={() => setSidebarOpen((open) => !open)}
          aria-label={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
          aria-controls="chat-sidebar"
          aria-expanded={sidebarOpen}
          title="Toggle sidebar (⌘B)"
        >
          <Icon name="sidebar" size={19} />
        </button>
        <div className="window-title">Loke</div>
      </header>

      <div className="app-region">
        <nav className="icon-rail" aria-label="Workspace">
          <div className="rail-top">
            {railItems.map((item) => (
              <button
                key={item.id}
                className={[
                  "rail-button",
                  section === item.id ? "selected" : "",
                ].join(" ")}
                onClick={() => {
                  setSection(item.id);
                  setProfileOpen(false);
                }}
                aria-label={item.label}
                title={item.label}
                aria-current={section === item.id ? "page" : undefined}
              >
                <Icon name={item.icon} size={20} />
              </button>
            ))}
          </div>
          <div className="profile-anchor" ref={profileRef}>
            <button
              className={["profile-button", profileOpen ? "selected" : ""].join(
                " ",
              )}
              onClick={() => setProfileOpen((open) => !open)}
              aria-label="Open profile menu"
              aria-haspopup="menu"
              aria-expanded={profileOpen}
              title="Profile"
            >
              {profileName.slice(0, 1).toUpperCase()}
            </button>
            {profileOpen && (
              <div
                className="profile-menu"
                role="menu"
                aria-label="Profile menu"
              >
                <div className="profile-menu-heading">
                  <span className="profile-menu-avatar">
                    {profileName.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="profile-menu-name">{profileName}</span>
                </div>
                <button
                  role="menuitem"
                  onClick={() => {
                    setDialog("settings");
                    setProfileOpen(false);
                  }}
                >
                  <Icon name="settings" size={20} />
                  Settings
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    setDialog("logout");
                    setProfileOpen(false);
                  }}
                >
                  <Icon name="logout" size={20} />
                  Log out
                </button>
              </div>
            )}
          </div>
        </nav>

        <div className="workspace-frame">
          <aside
            className="chat-sidebar"
            id="chat-sidebar"
            aria-label="Chats and folders"
            aria-hidden={!sidebarOpen}
            inert={!sidebarOpen}
          >
            <div className="sidebar-topline">
              <span className="sidebar-brand">Loke</span>
              <button
                className="icon-button sidebar-search"
                onClick={() => setSearchOpen((open) => !open)}
                aria-label="Search chats"
                title="Search chats (⌘K)"
              >
                <Icon name="search" size={19} />
              </button>
            </div>
            {searchOpen && (
              <div className="search-field">
                <Icon name="search" size={16} />
                <input
                  autoFocus
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search chats"
                  aria-label="Search chats"
                />
                <button
                  className="search-close"
                  onClick={() => {
                    setSearch("");
                    setSearchOpen(false);
                  }}
                  aria-label="Close search"
                >
                  <Icon name="close" size={14} />
                </button>
              </div>
            )}
            <div className="sidebar-scroll">
              <section className="sidebar-section" aria-label="Folders">
                <div className="section-heading">
                  <h2>Folders</h2>
                  <button
                    className="section-add"
                    onClick={() => setAddingFolder(true)}
                    aria-label="Add folder"
                    title="Add folder"
                  >
                    <Icon name="plus" size={16} />
                  </button>
                </div>
                {folders.map((folder) => {
                  const folderChats = chats.filter(
                    (chat) => chat.folderId === folder.id && matches(chat),
                  );
                  if (
                    search &&
                    !folder.name.toLowerCase().includes(search.toLowerCase()) &&
                    folderChats.length === 0
                  )
                    return null;
                  return (
                    <div key={folder.id} className="folder-group">
                      <button
                        className="folder-button"
                        onClick={() =>
                          setExpandedFolders((items) => ({
                            ...items,
                            [folder.id]: !items[folder.id],
                          }))
                        }
                        aria-expanded={!!expandedFolders[folder.id]}
                      >
                        <Icon name="folder" size={19} />
                        <span>{folder.name}</span>
                        <span
                          className={[
                            "folder-chevron",
                            expandedFolders[folder.id] ? "expanded" : "",
                          ].join(" ")}
                        >
                          <Icon name="chevron" size={14} />
                        </span>
                      </button>
                      {expandedFolders[folder.id] &&
                        folderChats.map((chat) => chatButton(chat, true))}
                    </div>
                  );
                })}
                {addingFolder && (
                  <form className="add-folder-form" onSubmit={addFolder}>
                    <input
                      autoFocus
                      value={folderName}
                      onChange={(event) => setFolderName(event.target.value)}
                      placeholder="Folder name"
                      aria-label="Folder name"
                      maxLength={40}
                      onKeyDown={(event) => {
                        if (event.key === "Escape") setAddingFolder(false);
                      }}
                    />
                    <button type="submit" aria-label="Save folder">
                      <Icon name="check" size={16} />
                    </button>
                  </form>
                )}
              </section>
              {recent.length > 0 && (
                <section className="sidebar-section" aria-label="Recent chats">
                  <h2>Recents</h2>
                  {recent.map((chat) => chatButton(chat))}
                </section>
              )}
              {workspace.hasMoreChats && (
                <button
                  onClick={() => void workspace.loadMoreChats()}
                  disabled={busy}
                >
                  Load more chats
                </button>
              )}
              {search &&
                recent.length === 0 &&
                !folders.some((folder) =>
                  chats.some(
                    (chat) => chat.folderId === folder.id && matches(chat),
                  ),
                ) && <p className="no-results">No matching chats</p>}
            </div>
          </aside>

          <main className="conversation" aria-label="Loke workspace">
            <div className="conversation-topline">
              <button
                className="icon-button"
                aria-label="New chat"
                disabled={busy || media.state !== "idle"}
                onClick={() => {
                  setSection("chats");
                  setActiveChatId(null);
                  setDraft("");
                  setInputLabel("");
                  setInputMode("text");
                }}
              >
                <Icon name="compose" />
              </button>
              {activeChat && (
                <label className="chat-folder-label">
                  Folder{" "}
                  <select
                    aria-label="Move chat to folder"
                    disabled={busy}
                    value={activeChat.folderId || ""}
                    onChange={(e) =>
                      void workspace
                        .moveChat(activeChat, e.target.value)
                        .catch((e) => workspace.setError(e.message))
                    }
                  >
                    <option value="">Recents</option>
                    {folders.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <button
                className="icon-button mobile-sidebar-toggle"
                onClick={() => setSidebarOpen((open) => !open)}
                aria-label="Toggle sidebar"
              >
                <Icon name="sidebar" size={19} />
              </button>
            </div>
            {!workspace.ready && (
              <p className="workspace-status" role="status">
                Connecting to local memory…
              </p>
            )}
            {(error || media.error) && (
              <div className="workspace-status" role="alert">
                {error || media.error}
                {workspace.canRetry && (
                  <>
                    <button
                      onClick={() =>
                        void workspace.retry().then((result) => {
                          if (result.ok && result.chatId) {
                            setActiveChatId(result.chatId);
                            setDraft("");
                            setInputLabel("");
                            setInputMode("text");
                          }
                        })
                      }
                      disabled={busy}
                    >
                      Retry same save
                    </button>
                    <button onClick={workspace.discardRetry} disabled={busy}>
                      Discard pending action
                    </button>
                  </>
                )}
              </div>
            )}
            {workspace.ready && !view?.storage_consent ? (
              <form
                className="setup-panel"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (storageConsent)
                    void workspace
                      .setup(goal)
                      .catch((e) => workspace.setError(e.message));
                }}
              >
                <h1>Set up your local learning memory</h1>
                <p>
                  This MVP teaches neural signaling. Chats, confirmed
                  transcripts, and extracted notes stay in local PostgreSQL
                  until you delete your history.
                </p>
                <label htmlFor="learning-goal">Learning goal</label>
                <input
                  id="learning-goal"
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  minLength={3}
                  maxLength={500}
                  required
                />
                <label>
                  <input
                    type="checkbox"
                    checked={storageConsent}
                    onChange={(e) => setStorageConsent(e.target.checked)}
                    required
                  />{" "}
                  Save my learning history on this Mac
                </label>
                <button disabled={busy || !storageConsent}>
                  Save goal and start
                </button>
              </form>
            ) : section === "chats" ? (
              <>
                <div
                  className={[
                    "conversation-body",
                    activeChat?.messages.length ? "has-messages" : "is-empty",
                  ].join(" ")}
                >
                  {activeChat?.messages.length ? (
                    <div className="message-list">
                      {activeChat.hasMore && (
                        <button
                          disabled={busy}
                          onClick={() => void workspace.loadEarlier(activeChat)}
                        >
                          Load earlier messages
                        </button>
                      )}
                      {activeChat.messages.map((message) => (
                        <article
                          className={["message", message.role].join(" ")}
                          key={message.id}
                        >
                          {message.role === "loke" && (
                            <div className="message-mark" aria-label="Loke">
                              <Icon name="spark" size={19} />
                            </div>
                          )}
                          <p>{message.text}</p>
                        </article>
                      ))}
                      <div ref={messagesEndRef} />
                    </div>
                  ) : (
                    <SeasonsEmptyState />
                  )}
                </div>
                <div className="composer-zone">
                  <form
                    className="composer"
                    onSubmit={sendMessage}
                    aria-busy={busy || media.state !== "idle"}
                  >
                    <input
                      type="file"
                      hidden
                      ref={media.fileRef}
                      accept=".txt,.md,.pdf,.mp3,.mp4,.m4a,.wav,.webm"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        if (
                          file &&
                          (!draft.trim() ||
                            window.confirm(
                              "Replace the current draft with this file's text?",
                            ))
                        )
                          void media.process(file);
                      }}
                    />
                    {inputLabel && (
                      <div className="draft-provenance">
                        {inputMode === "voice"
                          ? "Voice transcript"
                          : "Attachment"}
                        : {inputLabel}. Review and edit before sending.{" "}
                        <button
                          type="button"
                          onClick={() => {
                            setDraft("");
                            setInputLabel("");
                            setInputMode("text");
                          }}
                        >
                          Discard draft
                        </button>
                      </div>
                    )}
                    <div className="media-options">
                      <label>
                        <input
                          type="checkbox"
                          checked={media.consent}
                          onChange={(e) => {
                            media.cancel();
                            media.setConsent(e.target.checked);
                          }}
                        />{" "}
                        Allow this session's audio to be sent to OpenAI for
                        transcription. Audio is not retained by Loke.
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={speak}
                          onChange={(e) => {
                            setSpeak(e.target.checked);
                            if (!e.target.checked)
                              window.speechSynthesis?.cancel();
                          }}
                        />{" "}
                        Read replies aloud using this browser's voice
                      </label>
                      {!workspace.capabilities?.audio_available && (
                        <span>
                          Voice needs OPENAI_API_KEY and FFmpeg on the backend.
                          Text and document input work without them.
                        </span>
                      )}
                    </div>
                    <div role="status" aria-live="polite">
                      {busy
                        ? "Saving to local memory…"
                        : media.state !== "idle"
                          ? `${media.state}…`
                          : ""}
                      {media.state !== "idle" && (
                        <button type="button" onClick={media.cancel}>
                          Cancel audio or upload
                        </button>
                      )}
                    </div>
                    <label className="sr-only" htmlFor="message-input">
                      Message Loke
                    </label>
                    <textarea
                      id="message-input"
                      ref={composerRef}
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (
                          event.key === "Enter" &&
                          !event.shiftKey &&
                          !event.nativeEvent.isComposing
                        ) {
                          event.preventDefault();
                          event.currentTarget.form?.requestSubmit();
                        }
                      }}
                      placeholder="Ask anything"
                      rows={2}
                      maxLength={15000}
                      disabled={busy || media.state !== "idle"}
                      aria-describedby="composer-help"
                    />
                    <div className="composer-actions">
                      <div className="composer-left">
                        <button
                          className="composer-icon"
                          type="button"
                          aria-label="Add attachment"
                          title="Add attachment"
                          disabled={
                            busy ||
                            !view?.storage_consent ||
                            media.state !== "idle"
                          }
                          onClick={() => media.fileRef.current?.click()}
                        >
                          <Icon name="plus" size={21} />
                        </button>
                        <span className="composer-hint" id="composer-help">
                          TXT, Markdown, PDF or audio. Review before Send.
                        </span>
                      </div>
                      <div className="composer-right">
                        <button
                          className="composer-icon"
                          type="button"
                          aria-label={
                            media.state === "recording"
                              ? "Stop recording and transcribe"
                              : "Voice input"
                          }
                          title="Voice input"
                          disabled={
                            busy ||
                            !media.consent ||
                            !workspace.capabilities?.audio_available ||
                            !["idle", "recording"].includes(media.state)
                          }
                          onClick={() => {
                            if (
                              !draft.trim() ||
                              window.confirm(
                                "Replace the draft with a voice transcript?",
                              )
                            )
                              void media.record();
                          }}
                        >
                          <Icon name="mic" size={20} />
                        </button>
                        {draft.trim() ? (
                          <button
                            className="send-button"
                            type="submit"
                            aria-label="Send message"
                            disabled={
                              busy ||
                              media.state !== "idle" ||
                              workspace.canRetry
                            }
                          >
                            <Icon name="send" size={17} />
                          </button>
                        ) : (
                          <button
                            className="voice-button"
                            type="button"
                            aria-label={
                              media.state === "recording"
                                ? "Stop recording and transcribe"
                                : "Start voice mode"
                            }
                            disabled={
                              busy ||
                              !media.consent ||
                              !workspace.capabilities?.audio_available ||
                              !["idle", "recording"].includes(media.state)
                            }
                            onClick={() => {
                              setSpeak(true);
                              void media.record();
                            }}
                          >
                            <Icon name="voice" size={16} />
                          </button>
                        )}
                      </div>
                    </div>
                  </form>
                </div>
              </>
            ) : (
              <div className="learning-panel">
                <h1>
                  {section === "study"
                    ? "Your study space"
                    : "Your saved activity"}
                </h1>
                {section === "study" ? (
                  <>
                    <p>{view?.goal}</p>
                    <ul>
                      {view?.plan.map((p, i) => (
                        <li key={`${p.concept_id}-${i}`}>
                          <strong>{p.title}</strong>
                          <p>{p.reason}</p>
                          <small>
                            Evidence:{" "}
                            {p.reason_event_ids.join(", ") ||
                              "No assessment yet"}
                          </small>
                        </li>
                      ))}
                    </ul>
                    {view?.active_quiz && (
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          void workspace
                            .answer(answer)
                            .catch((e) => workspace.setError(e.message));
                        }}
                      >
                        <h2>Practice question</h2>
                        <p>{view.active_quiz.prompt}</p>
                        {Object.entries(view.active_quiz.options || {}).map(
                          ([key, value]) => (
                            <p key={key}>
                              {key}: {value}
                            </p>
                          ),
                        )}
                        <label htmlFor="quiz-answer">Your answer</label>
                        <input
                          id="quiz-answer"
                          value={answer}
                          onChange={(e) => setAnswer(e.target.value)}
                          required
                          maxLength={200}
                        />
                        <button disabled={busy || workspace.canRetry}>
                          Check answer
                        </button>
                        <p>{view.response}</p>
                      </form>
                    )}
                    <h2>Saved source excerpts</h2>
                    {view?.sources.map((source) => (
                      <article key={source.source_id}>
                        <h3>{source.title}</h3>
                        <p>{source.text}</p>
                      </article>
                    ))}
                  </>
                ) : (
                  <>
                    <p>
                      Most recent ten evidence records. Full conversations
                      remain available in Chats.
                    </p>
                    <ul>
                      {view?.events.map((event) => (
                        <li key={event.id}>
                          <strong>
                            {event.source}: {event.assessment}
                          </strong>
                          <p>{event.text}</p>
                          <time>
                            {new Date(event.occurred_at).toLocaleString()}
                          </time>
                        </li>
                      ))}
                    </ul>
                    <h2>Review reminders</h2>
                    <label>
                      <input
                        type="checkbox"
                        checked={view?.reminders_enabled || false}
                        disabled={busy}
                        onChange={(e) =>
                          void workspace
                            .reminders(e.target.checked)
                            .catch((e) => workspace.setError(e.message))
                        }
                      />{" "}
                      Enable in-app review reminders
                    </label>
                    <ul>
                      {view?.notifications.map((n) => (
                        <li key={n.id}>{n.title}</li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}
          </main>
        </div>
      </div>

      {dialog && (
        <div
          className="dialog-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setDialog(null);
          }}
        >
          <div
            className="dialog"
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="dialog-title"
          >
            <div className="dialog-header">
              <h2 id="dialog-title">
                {dialog === "settings" ? "Settings" : "Log out"}
              </h2>
              <button
                className="icon-button"
                onClick={() => setDialog(null)}
                aria-label="Close dialog"
              >
                <Icon name="close" size={19} />
              </button>
            </div>
            {dialog === "settings" ? (
              <div className="dialog-content">
                <p>Local profile: {profileName}</p>
                <p>
                  Chats and learning records are stored in PostgreSQL on this
                  Mac, with no automatic expiry. Optional live models and voice
                  processing send submitted content to their providers.
                </p>
                <button
                  disabled={busy || !view?.storage_consent}
                  onClick={() => {
                    if (
                      window.confirm(
                        "Permanently delete all local chats, sources, folders and learning history?",
                      )
                    ) {
                      media.cancel();
                      void workspace
                        .reset()
                        .then(() => setDialog(null))
                        .catch((e) => workspace.setError(e.message));
                    }
                  }}
                >
                  Delete all learning history
                </button>
              </div>
            ) : (
              <div className="dialog-content">
                <p>
                  This is a local, single-user workspace. There is no remote
                  account to sign out of. Close this window to leave; your saved
                  history remains on this Mac.
                </p>
                <button className="dialog-done" onClick={() => setDialog(null)}>
                  Done
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
