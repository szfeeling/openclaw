import { useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";
import { DEFAULT_API_BASE, loadRuntimeConfig } from "./runtimeConfig.js";
const DAY_SECONDS = 24 * 60 * 60;

function getProjectAvatarId(project) {
  if (!project) {
    return null;
  }
  return project.avatarId ?? project.avatar_id ?? null;
}

function getAvatarVoiceId(avatar) {
  if (!avatar) {
    return "";
  }
  return avatar.voiceId ?? avatar.voice_id ?? "";
}

function newMessageId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

function resolveTaskGroup(createdAt, nowSeconds) {
  if (typeof createdAt !== "number" || Number.isNaN(createdAt)) {
    return "unknown";
  }
  const age = Math.max(0, nowSeconds - createdAt);
  if (age <= DAY_SECONDS) {
    return "today";
  }
  if (age <= DAY_SECONDS * 7) {
    return "week";
  }
  return "earlier";
}

function buildTaskTree(projects) {
  const nowSeconds = Date.now() / 1000;
  const groups = {
    today: [],
    week: [],
    earlier: [],
    unknown: [],
  };

  const sorted = [...projects].toSorted((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0));
  for (const project of sorted) {
    groups[resolveTaskGroup(project.created_at, nowSeconds)].push(project);
  }

  const entries = [
    { id: "today", label: "Today", items: groups.today },
    { id: "week", label: "This Week", items: groups.week },
    { id: "earlier", label: "Earlier", items: groups.earlier },
    { id: "unknown", label: "Unsorted", items: groups.unknown },
  ];
  return entries.filter((entry) => entry.items.length > 0);
}

export default function App() {
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [projects, setProjects] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [avatars, setAvatars] = useState([]);
  const [messagesByProject, setMessagesByProject] = useState({});
  const [projectName, setProjectName] = useState("");
  const [messageInput, setMessageInput] = useState("");
  const [streamEnabled, setStreamEnabled] = useState(true);
  const [sending, setSending] = useState(false);
  const [healthStatus, setHealthStatus] = useState("Connecting...");
  const [collapsedGroups, setCollapsedGroups] = useState({});

  const messagesRef = useRef(null);
  const taskTree = useMemo(() => buildTaskTree(projects), [projects]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedId) ?? null,
    [projects, selectedId],
  );
  const selectedMessages = selectedId ? (messagesByProject[selectedId] ?? []) : [];
  const selectedAvatar = useMemo(() => {
    const avatarId = getProjectAvatarId(selectedProject);
    return avatars.find((avatar) => avatar.id === avatarId) ?? null;
  }, [avatars, selectedProject]);

  useEffect(() => {
    if (!messagesRef.current) {
      return;
    }
    messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [selectedMessages]);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      const runtime = await loadRuntimeConfig();
      if (cancelled) {
        return;
      }
      const base = runtime.apiBase;
      setApiBase(base);

      try {
        const health = await fetchJson(`${base}/api/health`);
        if (!cancelled) {
          setHealthStatus(`Gateway: ${health.openclaw_base_url}`);
        }
      } catch {
        if (!cancelled) {
          setHealthStatus("Gateway unreachable");
        }
      }

      try {
        const avatarList = await fetchJson(`${base}/api/avatars`);
        if (!cancelled) {
          setAvatars(avatarList);
        }
      } catch {
        if (!cancelled) {
          setAvatars([]);
        }
      }

      try {
        const projectList = await fetchJson(`${base}/api/projects`);
        if (cancelled) {
          return;
        }
        setProjects(projectList);
        if (projectList.length > 0) {
          setSelectedId((current) => current ?? projectList[0].id);
        }
      } catch {
        if (!cancelled) {
          setProjects([]);
        }
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  function appendMessage(projectId, role, content) {
    setMessagesByProject((previous) => {
      const messages = previous[projectId] ?? [];
      return {
        ...previous,
        [projectId]: [...messages, { id: newMessageId(), role, content }],
      };
    });
  }

  function updateAssistantMessage(projectId, messageId, update) {
    setMessagesByProject((previous) => {
      const messages = previous[projectId] ?? [];
      return {
        ...previous,
        [projectId]: messages.map((entry) =>
          entry.id === messageId ? { ...entry, content: update(entry.content ?? "") } : entry,
        ),
      };
    });
  }

  async function createProject(event) {
    event.preventDefault();
    const name = projectName.trim();
    if (!name) {
      return;
    }

    const created = await fetchJson(`${apiBase}/api/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });

    setProjects((previous) => [created, ...previous]);
    setSelectedId(created.id);
    setProjectName("");
  }

  function toggleTaskGroup(groupId) {
    setCollapsedGroups((previous) => ({
      ...previous,
      [groupId]: !previous[groupId],
    }));
  }

  async function setProjectAvatar(avatarId) {
    if (!selectedId) {
      return;
    }
    const updated = await fetchJson(`${apiBase}/api/projects/${selectedId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ avatarId }),
    });
    setProjects((previous) =>
      previous.map((project) => (project.id === updated.id ? updated : project)),
    );
  }

  async function streamResponse(projectId, text, avatarId) {
    const assistantId = newMessageId();
    setMessagesByProject((previous) => {
      const messages = previous[projectId] ?? [];
      return {
        ...previous,
        [projectId]: [...messages, { id: assistantId, role: "assistant", content: "" }],
      };
    });

    const response = await fetch(`${apiBase}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId, message: text, avatarId }),
    });
    if (!response.ok || !response.body) {
      const body = await response.text();
      throw new Error(body || `Stream failed: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";

      for (const part of parts) {
        const lines = part.split("\n");
        for (const line of lines) {
          if (!line.startsWith("data:")) {
            continue;
          }
          const payload = line.slice(5).trim();
          if (!payload || payload === "[DONE]") {
            continue;
          }

          try {
            const event = JSON.parse(payload);
            if (event.type === "response.output_text.delta" && typeof event.delta === "string") {
              updateAssistantMessage(projectId, assistantId, (previous) => previous + event.delta);
            }
            if (event.type === "response.output_text.done" && typeof event.text === "string") {
              updateAssistantMessage(projectId, assistantId, () => event.text);
            }
            if (event.type === "response.error" && typeof event.error === "string") {
              const status = typeof event.status === "number" ? ` (${event.status})` : "";
              updateAssistantMessage(
                projectId,
                assistantId,
                () => `Error${status}: ${event.error}`,
              );
            }
          } catch {
            // Ignore malformed SSE events.
          }
        }
      }
    }
  }

  async function sendMessage() {
    if (!selectedId || sending) {
      return;
    }
    const text = messageInput.trim();
    if (!text) {
      return;
    }

    const project = projects.find((entry) => entry.id === selectedId);
    const avatarId = getProjectAvatarId(project);

    appendMessage(selectedId, "user", text);
    setMessageInput("");
    setSending(true);
    try {
      if (streamEnabled) {
        await streamResponse(selectedId, text, avatarId);
      } else {
        const result = await fetchJson(`${apiBase}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ projectId: selectedId, message: text, avatarId }),
        });
        appendMessage(selectedId, "assistant", result.reply ?? "");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      appendMessage(selectedId, "assistant", `Error: ${message}`);
    } finally {
      setSending(false);
    }
  }

  return (
    <div id="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-title">OpenClaw</div>
          <div className="brand-sub">Task Sessions</div>
        </div>
        <form className="project-form" onSubmit={createProject}>
          <input
            type="text"
            placeholder="New task"
            autoComplete="off"
            value={projectName}
            onChange={(event) => setProjectName(event.target.value)}
          />
          <button type="submit">Create</button>
        </form>

        <div className="task-tree">
          {taskTree.length === 0 ? (
            <div className="empty">No tasks yet. Create one.</div>
          ) : (
            taskTree.map((group) => {
              const collapsed = Boolean(collapsedGroups[group.id]);
              return (
                <div key={group.id} className="tree-group">
                  <button
                    type="button"
                    className="tree-branch"
                    onClick={() => toggleTaskGroup(group.id)}
                  >
                    <span className={`tree-caret ${collapsed ? "collapsed" : ""}`}>▾</span>
                    <span className="tree-label">{group.label}</span>
                    <span className="tree-count">{group.items.length}</span>
                  </button>
                  {!collapsed && (
                    <div className="tree-children">
                      {group.items.map((project) => (
                        <button
                          key={project.id}
                          type="button"
                          className={`tree-leaf ${project.id === selectedId ? "active" : ""}`}
                          onClick={() => setSelectedId(project.id)}
                        >
                          <div className="tree-leaf-name">{project.name}</div>
                          <div className="tree-leaf-meta">{project.session_key}</div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        <div className="sidebar-footer">
          <div className="status">{healthStatus}</div>
        </div>
      </aside>

      <main className="chat">
        <header className="chat-header">
          <div>
            <div className="chat-title">
              {selectedProject ? selectedProject.name : "Select a task"}
            </div>
            <div className="chat-meta">
              {selectedProject
                ? `Session: ${selectedProject.session_key} · Avatar: ${
                    selectedAvatar ? selectedAvatar.name : "Unknown"
                  }`
                : "Session: -"}
            </div>
          </div>
          <label className="toggle">
            <input
              type="checkbox"
              checked={streamEnabled}
              onChange={(event) => setStreamEnabled(event.target.checked)}
            />
            <span>Stream</span>
          </label>
        </header>

        <section className="avatars">
          <div className="avatars-title">Digital Humans</div>
          <div className="avatars-list">
            {!selectedId ? (
              <div className="empty">Select a task to choose an avatar.</div>
            ) : avatars.length === 0 ? (
              <div className="empty">No avatars available.</div>
            ) : (
              avatars.map((avatar) => (
                <button
                  key={avatar.id}
                  type="button"
                  className={`avatar-card ${
                    getProjectAvatarId(selectedProject) === avatar.id ? "active" : ""
                  }`}
                  onClick={() => void setProjectAvatar(avatar.id)}
                >
                  <div className="avatar-name">{avatar.name}</div>
                  <div className="avatar-meta">{getAvatarVoiceId(avatar)}</div>
                </button>
              ))
            )}
          </div>
        </section>

        <section className="messages" ref={messagesRef}>
          {!selectedId ? (
            <div className="empty">Pick a task to start.</div>
          ) : selectedMessages.length === 0 ? (
            <div className="empty">No messages yet.</div>
          ) : (
            selectedMessages.map((message) => (
              <div key={message.id} className={`message ${message.role}`}>
                <div className="role">{message.role === "user" ? "You" : "OpenClaw"}</div>
                <div className="content">{message.content}</div>
              </div>
            ))
          )}
        </section>

        <footer className="composer">
          <textarea
            rows={3}
            placeholder="Describe the task you want done..."
            value={messageInput}
            disabled={sending || !selectedId}
            onChange={(event) => setMessageInput(event.target.value)}
            onKeyDown={(event) => {
              if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                event.preventDefault();
                void sendMessage();
              }
            }}
          />
          <button
            className="send"
            type="button"
            disabled={sending || !selectedId}
            onClick={() => void sendMessage()}
          >
            Send
          </button>
        </footer>
      </main>
    </div>
  );
}
