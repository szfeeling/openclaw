import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const projectListEl = document.getElementById("project-list");
const projectForm = document.getElementById("project-form");
const projectNameInput = document.getElementById("project-name");
const chatTitle = document.getElementById("chat-title");
const chatMeta = document.getElementById("chat-meta");
const messagesEl = document.getElementById("messages");
const messageInput = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const healthStatus = document.getElementById("health-status");
const streamToggle = document.getElementById("stream-toggle");
const avatarsEl = document.getElementById("avatars");

const state = {
  projects: [],
  selectedId: null,
  messages: new Map(),
  sending: false,
  avatars: [],
};

function getMessages(projectId) {
  if (!state.messages.has(projectId)) {
    state.messages.set(projectId, []);
  }
  return state.messages.get(projectId);
}

function getProjectAvatarId(project) {
  if (!project) return null;
  return project.avatarId ?? project.avatar_id ?? null;
}

function getAvatarVoiceId(avatar) {
  if (!avatar) return "";
  return avatar.voiceId ?? avatar.voice_id ?? "";
}

function renderProjects() {
  projectListEl.innerHTML = "";
  if (state.projects.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No projects yet. Create one.";
    projectListEl.appendChild(empty);
    return;
  }

  state.projects.forEach((project) => {
    const item = document.createElement("button");
    item.className = "project-item";
    if (project.id === state.selectedId) {
      item.classList.add("active");
    }
    item.type = "button";
    item.innerHTML = `
      <div class="project-name">${project.name}</div>
      <div class="project-meta">${project.session_key}</div>
    `;
    item.addEventListener("click", () => selectProject(project.id));
    projectListEl.appendChild(item);
  });
}

function renderMessages() {
  messagesEl.innerHTML = "";
  if (!state.selectedId) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Pick a project to start.";
    messagesEl.appendChild(empty);
    return;
  }
  const messages = getMessages(state.selectedId);
  if (messages.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No messages yet.";
    messagesEl.appendChild(empty);
    return;
  }

  messages.forEach((msg) => {
    const bubble = document.createElement("div");
    bubble.className = `message ${msg.role}`;
    const role = document.createElement("div");
    role.className = "role";
    role.textContent = msg.role === "user" ? "You" : "OpenClaw";
    const content = document.createElement("div");
    content.className = "content";
    content.textContent = msg.content;
    bubble.appendChild(role);
    bubble.appendChild(content);
    messagesEl.appendChild(bubble);
  });
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderAvatars() {
  avatarsEl.innerHTML = "";
  if (!state.selectedId) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Select a project to choose an avatar.";
    avatarsEl.appendChild(empty);
    return;
  }
  if (state.avatars.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No avatars available.";
    avatarsEl.appendChild(empty);
    return;
  }

  state.avatars.forEach((avatar) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "avatar-card";
    const project = state.projects.find((p) => p.id === state.selectedId);
    if (project && getProjectAvatarId(project) === avatar.id) {
      card.classList.add("active");
    }
    card.innerHTML = `\n      <div class="avatar-name">${avatar.name}</div>\n      <div class="avatar-meta">${getAvatarVoiceId(avatar)}</div>\n    `;\n    card.addEventListener("click", () => setProjectAvatar(avatar.id));
    avatarsEl.appendChild(card);
  });
}

function setSending(value) {
  state.sending = value;
  sendBtn.disabled = value || !state.selectedId;
  messageInput.disabled = value || !state.selectedId;
}

function selectProject(projectId) {
  state.selectedId = projectId;
  const project = state.projects.find((p) => p.id === projectId);
  chatTitle.textContent = project ? project.name : "Select a project";
  if (project) {
    const avatarId = getProjectAvatarId(project);
    const avatar = state.avatars.find((a) => a.id === avatarId);
    const avatarName = avatar ? avatar.name : "Unknown";
    chatMeta.textContent = `Session: ${project.session_key} · Avatar: ${avatarName}`;
  } else {
    chatMeta.textContent = "Session: -";
  }
  renderProjects();
  renderAvatars();
  renderMessages();
  setSending(false);
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed: ${res.status}`);
  }
  return res.json();
}

async function loadProjects() {
  const data = await fetchJson(`${API_BASE}/api/projects`);
  state.projects = data;
  if (!state.selectedId && state.projects.length > 0) {
    selectProject(state.projects[0].id);
  } else {
    renderProjects();
    renderAvatars();
    renderMessages();
  }
}

async function loadAvatars() {
  try {
    const data = await fetchJson(`${API_BASE}/api/avatars`);
    state.avatars = data;
  } catch (err) {
    state.avatars = [];
  }
  renderAvatars();
}

async function createProject(name) {
  const payload = { name };
  const project = await fetchJson(`${API_BASE}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  state.projects = [project, ...state.projects];
  selectProject(project.id);
}

async function setProjectAvatar(avatarId) {
  if (!state.selectedId) return;
  const projectId = state.selectedId;
  const payload = { avatarId };
  const project = await fetchJson(`${API_BASE}/api/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  state.projects = state.projects.map((p) => (p.id === project.id ? project : p));
  selectProject(project.id);
}

async function loadHealth() {
  try {
    const data = await fetchJson(`${API_BASE}/api/health`);
    healthStatus.textContent = `Gateway: ${data.openclaw_base_url}`;
  } catch (err) {
    healthStatus.textContent = "Gateway unreachable";
  }
}

function appendMessage(projectId, role, content) {
  const messages = getMessages(projectId);
  messages.push({ role, content });
  renderMessages();
}

async function sendMessage() {
  if (!state.selectedId || state.sending) return;
  const text = messageInput.value.trim();
  if (!text) return;

  const projectId = state.selectedId;
  appendMessage(projectId, "user", text);
  messageInput.value = "";
  setSending(true);

  try {
    if (streamToggle.checked) {
      await streamResponse(projectId, text);
    } else {
      const project = state.projects.find((p) => p.id === projectId);
      const avatarId = getProjectAvatarId(project);
      const res = await fetchJson(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId, message: text, avatarId }),
      });
      appendMessage(projectId, "assistant", res.reply || "");
    }
  } catch (err) {
    appendMessage(projectId, "assistant", `Error: ${err.message}`);
  } finally {
    setSending(false);
  }
}

async function streamResponse(projectId, message) {
  const project = state.projects.find((p) => p.id === projectId);
  const avatarId = getProjectAvatarId(project);
  const messages = getMessages(projectId);
  const assistant = { role: "assistant", content: "" };
  messages.push(assistant);
  renderMessages();

  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ projectId, message, avatarId }),
  });

  if (!res.ok || !res.body) {
    const text = await res.text();
    throw new Error(text || `Stream failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const part of parts) {
      const lines = part.split("\n");
      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if (!data || data === "[DONE]") continue;
        try {
          const event = JSON.parse(data);
          if (event.type === "response.output_text.delta") {
            assistant.content += event.delta || "";
            renderMessages();
          }
          if (event.type === "response.output_text.done") {
            if (event.text) {
              assistant.content = event.text;
              renderMessages();
            }
          }
        } catch (err) {
          // Ignore malformed events
        }
      }
    }
  }
}

projectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = projectNameInput.value.trim();
  if (!name) return;
  projectNameInput.value = "";
  await createProject(name);
});

sendBtn.addEventListener("click", sendMessage);
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    sendMessage();
  }
});

await loadHealth();
await loadAvatars();
await loadProjects();
renderProjects();
renderAvatars();
renderMessages();
setSending(false);
