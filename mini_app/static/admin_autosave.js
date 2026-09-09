(() => {
  const DELAY = 1200;

  const autosaveKey = (form) => {
    const action = form.elements.action?.value || "form";
    const identity = form.dataset.autosaveId || "new";
    return `nastaunik:admin-draft:${location.pathname}:${action}:${identity}`;
  };

  const serializableFields = (form) => [...form.elements].filter((field) => {
    if (!field.name || field.disabled) return false;
    if (["file", "submit", "button", "reset"].includes(field.type)) return false;
    return !["action", "ajax", "autosave"].includes(field.name);
  });

  const serialize = (form) => {
    const values = {};
    serializableFields(form).forEach((field) => {
      if (field.type === "checkbox" || field.type === "radio") {
        values[field.name] = field.checked;
      } else {
        values[field.name] = field.value;
      }
    });
    const editor = form.querySelector("[contenteditable][data-placeholder]");
    if (editor) values.__richText = editor.innerHTML;
    return values;
  };

  const restore = (form, values) => {
    serializableFields(form).forEach((field) => {
      if (!(field.name in values)) return;
      if (field.type === "checkbox" || field.type === "radio") {
        field.checked = Boolean(values[field.name]);
      } else {
        field.value = values[field.name] ?? "";
      }
    });
    const editor = form.querySelector("[contenteditable][data-placeholder]");
    if (editor && typeof values.__richText === "string") editor.innerHTML = values.__richText;
  };

  const setState = (form, text, error = false) => {
    const state = form.querySelector("[data-save-state]") || form.querySelector(".editor-save");
    if (!state) return;
    state.textContent = text;
    state.classList.toggle("is-error", error);
  };

  const remember = (form) => {
    try {
      localStorage.setItem(autosaveKey(form), JSON.stringify({savedAt: Date.now(), values: serialize(form)}));
    } catch (_) {}
  };

  const clearRemembered = (form) => {
    try { localStorage.removeItem(autosaveKey(form)); } catch (_) {}
  };

  const send = async (form) => {
    if (!form.dataset.autosaveId) {
      setState(form, "Черновик сохранён в этом браузере. Нажмите «Сохранить», чтобы создать запись.");
      return;
    }
    if (form.__autosaveBusy) {
      form.__autosaveQueued = true;
      return;
    }
    form.__autosaveBusy = true;
    form.__autosaveQueued = false;
    setState(form, "Сохраняем…");
    try {
      if (typeof window.sync === "function" && form.querySelector("[contenteditable]")) window.sync();
      const body = new FormData(form);
      [...body.keys()].forEach((key) => {
        const field = form.elements[key];
        if (field && field.type === "file") body.delete(key);
      });
      body.set("autosave", "1");
      body.set("ajax", "1");
      const response = await fetch(form.action || location.href, {
        method: "POST",
        body,
        credentials: "same-origin",
        headers: {"X-Requested-With": "XMLHttpRequest"},
      });
      if (!response.ok) throw new Error(await response.text());
      clearRemembered(form);
      setState(form, `Сохранено в ${new Date().toLocaleTimeString("ru-RU", {hour: "2-digit", minute: "2-digit"})}`);
    } catch (error) {
      setState(form, "Не удалось сохранить. Черновик остался в этом браузере.", true);
    } finally {
      form.__autosaveBusy = false;
      if (form.__autosaveQueued) schedule(form);
    }
  };

  const schedule = (form) => {
    remember(form);
    setState(form, form.dataset.autosaveId ? "Есть несохранённые изменения…" : "Черновик сохранён в этом браузере");
    clearTimeout(form.__autosaveTimer);
    form.__autosaveTimer = setTimeout(() => send(form), DELAY);
  };

  window.scheduleAdminAutosave = schedule;

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("form[data-autosave]").forEach((form) => {
      try {
        const saved = JSON.parse(localStorage.getItem(autosaveKey(form)) || "null");
        if (saved?.values) {
          restore(form, saved.values);
          setState(form, "Восстановлен несохранённый черновик");
        }
      } catch (_) {}

      form.addEventListener("input", (event) => {
        if (event.target.type === "file") return;
        if (form.id === "article-form" && event.target.isContentEditable) {
          remember(form);
          return;
        }
        schedule(form);
      });
      form.addEventListener("change", (event) => {
        if (event.target.type !== "file") schedule(form);
      });
      form.addEventListener("submit", () => clearRemembered(form));
    });
  });
})();
