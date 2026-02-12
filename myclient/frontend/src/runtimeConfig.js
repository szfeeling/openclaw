export const DEFAULT_API_BASE = "http://localhost:8000";

function normalizeApiBase(value) {
  if (typeof value !== "string") {
    return "";
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  return trimmed.replace(/\/+$/, "");
}

export async function loadRuntimeConfig() {
  let fileApiBase = "";
  try {
    const response = await fetch("/app-config.json", { cache: "no-store" });
    if (response.ok) {
      const payload = await response.json();
      if (payload && typeof payload === "object") {
        fileApiBase = normalizeApiBase(payload.apiBase);
      }
    }
  } catch {
    // Ignore missing runtime config; defaults are handled below.
  }

  const envApiBase = normalizeApiBase(import.meta.env.VITE_API_BASE);
  const apiBase = envApiBase || fileApiBase || DEFAULT_API_BASE;
  return { apiBase };
}
