"use client";

import dynamic from "next/dynamic";
import { ChatMarkdown } from "./chat-markdown";
import { useRuntimeChat } from "./use-runtime-chat";
import { RuntimeElement } from "./runtime-elements";
import type { RuntimeDisplay } from "./runtime-client";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

const Seasons = dynamic(() => import("anatomy-figures").then((module) => module.Seasons), {
  ssr: false,
});

function SeasonsEmptyState() {
  const figureRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = figureRef.current;
    if (!container) return;

    const sheet = new CSSStyleSheet();
    sheet.replaceSync('[data-corner="title"], [data-corner="hint"] { display: none; }');
    let shadowRoot: ShadowRoot | null = null;
    let frame = 0;

    const attachSheet = () => {
      frame = 0;
      const nextRoot = container.querySelector("[data-anatomy-figure]")?.shadowRoot;
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
  | "stop"
  | "settings"
  | "logout"
  | "close"
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
    stop: <rect x="6" y="6" width="12" height="12" rx="1" fill="currentColor" stroke="none" />,
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

type Message = { id: string; role: "user" | "loke"; text: string; runtime?: RuntimeDisplay };
type Chat = {
  id: string;
  title: string;
  folderId?: string;
  messages: Message[];
};
type Folder = { id: string; name: string };
type Section = "chats" | "study" | "activity";

const initialFolders: Folder[] = [
  { id: "neuroscience", name: "Neuroscience" },
  { id: "study-plans", name: "Study plans" },
];

const initialChats: Chat[] = [
  {
    id: "neural-signaling",
    title: "Understanding neural signaling",
    folderId: "neuroscience",
    messages: [
      {
        id: "a",
        role: "user",
        text: "Help me understand how neurons release neurotransmitters.",
      },
      {
        id: "b",
        role: "loke",
        text: "Let's start with the signal that reaches the end of a neuron. An action potential travels along the axon and triggers the next steps at the synapse.",
      },
    ],
  },
  {
    id: "action-potentials",
    title: "How action potentials work",
    folderId: "neuroscience",
    messages: [
      {
        id: "a",
        role: "user",
        text: "What makes an action potential move along an axon?",
      },
      {
        id: "b",
        role: "loke",
        text: "A change in voltage opens nearby sodium channels. That change triggers the next section of membrane, so the signal travels along the axon.",
      },
    ],
  },
  {
    id: "synapses",
    title: "What happens at a synapse?",
    folderId: "neuroscience",
    messages: [],
  },
  {
    id: "review-plan",
    title: "A ten-minute review plan",
    folderId: "study-plans",
    messages: [],
  },
  {
    id: "prerequisites",
    title: "Which concept should I review?",
    messages: [],
  },
];

const railItems: { id: Section; label: string; icon: IconName }[] = [
  { id: "chats", label: "Chats", icon: "home" },
  { id: "study", label: "Study", icon: "book" },
  { id: "activity", label: "Activity", icon: "clock" },
];

export default function Workspace() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [section, setSection] = useState<Section>("chats");
  const [chats, setChats] = useState<Chat[]>(initialChats);
  const runtimeChat = useRuntimeChat((chatId, requestId, display) => {
    setChats((items) => items.map((chat) => {
      if (chat.id !== chatId) return chat;
      const id = `runtime-${requestId}`;
      const message: Message = { id, role: "loke", text: display.text, runtime: display };
      const existing = chat.messages.some((item) => item.id === id);
      return { ...chat, messages: existing ? chat.messages.map((item) => item.id === id ? message : item)
        : [...chat.messages, message] };
    }));
  });
  const [folders, setFolders] = useState<Folder[]>(initialFolders);
  const [expandedFolders, setExpandedFolders] = useState<
    Record<string, boolean>
  >({ neuroscience: true, "study-plans": true });
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [addingFolder, setAddingFolder] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const [dialog, setDialog] = useState<"settings" | "logout" | null>(null);
  const [profileName, setProfileName] = useState("Learner");
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeChat = chats.find((chat) => chat.id === activeChatId);
  const activeRun = activeChatId ? runtimeChat.runs[activeChatId] : undefined;
  const chatBusy = activeRun?.phase === "running" || activeRun?.phase === "resetting" || activeRun?.phase === "offline";
  const matches = (chat: Chat) =>
    chat.title.toLowerCase().includes(search.trim().toLowerCase());
  const recent = chats.filter(
    (chat) => !chat.folderId && matches(chat),
  );

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
    setDraft("");
  }

  function startNewChat() {
    setSection("chats");
    setActiveChatId(null);
    setDraft("");
    setProfileOpen(false);
  }

  function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submitChatMessage(draft.trim());
  }

  function submitChatMessage(text: string, displayText = text) {
    if (!text || chatBusy) return false;
    const chatId = activeChatId || crypto.randomUUID();
    if (!runtimeChat.submit(chatId, text)) return false;
    const message: Message = { id: crypto.randomUUID(), role: "user", text: displayText };
    if (activeChatId) {
      setChats((items) =>
        items.map((chat) =>
          chat.id === activeChatId
            ? { ...chat, messages: [...chat.messages, message] }
            : chat,
        ),
      );
    } else {
      const id = chatId;
      setChats((items) => [
        {
          id,
          title: displayText.length > 36 ? displayText.slice(0, 36).trimEnd() + "…" : displayText,
          messages: [message],
        },
        ...items,
      ]);
      setActiveChatId(id);
    }
    setDraft("");
    return true;
  }

  function addFolder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = folderName.trim();
    if (!name) return;
    const id = crypto.randomUUID();
    setFolders((items) => [...items, { id, name }]);
    setExpandedFolders((items) => ({ ...items, [id]: true }));
    setFolderName("");
    setAddingFolder(false);
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
          >
              <div className="sidebar-topline">
                <span className="sidebar-brand">
                  Loke
                </span>
                <button
                  className="icon-button sidebar-search"
                  onClick={() => setSearchOpen((open) => !open)}
                  aria-label="Search chats"
                  title="Search chats (⌘K)"
                >
                  <Icon name="search" size={19} />
                </button>
              </div>
              <button className="new-chat-button" type="button" onClick={startNewChat}>
                <Icon name="plus" size={18} />
                <span>New chat</span>
              </button>
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
                      (chat) =>
                        chat.folderId === folder.id &&
                        matches(chat),
                    );
                    if (
                      search &&
                      !folder.name
                        .toLowerCase()
                        .includes(search.toLowerCase()) &&
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
                  <section
                    className="sidebar-section"
                    aria-label="Recent chats"
                  >
                    <h2>Recents</h2>
                    {recent.map((chat) => chatButton(chat))}
                  </section>
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
                className="icon-button mobile-sidebar-toggle"
                onClick={() => setSidebarOpen((open) => !open)}
                aria-label="Toggle sidebar"
              >
                <Icon name="sidebar" size={19} />
              </button>
            </div>
            {section === "chats" ? (
              <>
                <div
                  className={[
                    "conversation-body",
                    activeChat?.messages.length ? "has-messages" : "is-empty",
                  ].join(" ")}
                >
                  {activeChat?.messages.length ? (
                    <div className="message-list">
                      {activeChat.messages.map((message) => (
                        <article
                          className={["message", message.role].join(" ")}
                          key={message.id}
                        >
                          <div className="message-content">
                            {message.runtime
                              ? message.runtime.blocks.map((block) => block.kind === "text" ? (
                                <ChatMarkdown key={block.id} text={block.text}
                                  streaming={!message.runtime?.outcome} />
                              ) : (
                                <RuntimeElement
                                  key={block.id}
                                  element={block.element}
                                  disabled={!!chatBusy || message.runtime?.outcome?.status !== "completed"}
                                  onChoose={(choice, question) => submitChatMessage(
                                    `Question: ${question}\nSelected choice: ${choice}`,
                                    choice,
                                  )}
                                />
                              ))
                              : message.text && (message.role === "loke"
                                ? <ChatMarkdown text={message.text} />
                                : <p>{message.text}</p>)}
                            {message.runtime?.outcome?.notice && (
                              <div className="response-status response-error" role="status">
                                {message.runtime.outcome.notice}
                              </div>
                            )}
                          </div>
                        </article>
                      ))}
                      {activeRun?.phase === "running" && (
                        <div className="response-status" role="status" aria-live="polite">
                          <span className="response-indicator" aria-hidden="true" />
                          <span>{activeRun.error || activeRun.display.progress || "Thinking"}</span>
                        </div>
                      )}
                      {activeRun?.phase === "offline" && (
                        <div className="response-status response-error" role="status" aria-live="polite">
                          <span>{activeRun.error || "Connection lost. Retry this response."}</span>
                          <button type="button" onClick={() => activeChatId && runtimeChat.retry(activeChatId)}>
                            Retry
                          </button>
                        </div>
                      )}
                      <div ref={messagesEndRef} />
                    </div>
                  ) : (
                    <SeasonsEmptyState />
                  )}
                </div>
                <div className="composer-zone">
                  <form className="composer" onSubmit={sendMessage}>
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
                    />
                    <div className="composer-actions">
                      <div className="composer-left">
                        <button
                          className="composer-icon"
                          type="button"
                          aria-label="Add attachment"
                          title="Add attachment"
                        >
                          <Icon name="plus" size={21} />
                        </button>
                      </div>
                      <div className="composer-right">
                        <button
                          className="composer-icon"
                          type="button"
                          aria-label="Voice input"
                          title="Voice input"
                        >
                          <Icon name="mic" size={20} />
                        </button>
                        {activeRun?.phase === "running" || activeRun?.phase === "offline" ? (
                          <button
                            className="stop-button"
                            type="button"
                            aria-label="Stop response"
                            title="Stop response"
                            onClick={() => activeChatId && void runtimeChat.cancel(activeChatId)}
                          >
                            <Icon name="stop" size={14} />
                          </button>
                        ) : draft.trim() ? (
                          <button
                            className="send-button"
                            type="submit"
                            aria-label="Send message"
                            disabled={!!chatBusy}
                          >
                            <Icon name="send" size={17} />
                          </button>
                        ) : (
                          <button
                            className="voice-button"
                            type="button"
                            aria-label="Start voice mode"
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
              <div className="section-empty">
                <div className="empty-mark">
                  <Icon
                    name={section === "study" ? "book" : "clock"}
                    size={30}
                  />
                </div>
                <h1>
                  {section === "study" ? "Your study space" : "Your activity"}
                </h1>
                <p>
                  {section === "study"
                    ? "Your learning materials will live here."
                    : "Your recent learning activity will appear here."}
                </p>
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
                <label htmlFor="profile-name">Profile name</label>
                <input
                  id="profile-name"
                  value={profileName}
                  onChange={(event) => setProfileName(event.target.value)}
                  maxLength={40}
                />
                <p>
                  Your profile and conversations are local interface
                  placeholders for now.
                </p>
              </div>
            ) : (
              <div className="dialog-content">
                <p>
                  Account sign-out can be connected when authentication is
                  added.
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
