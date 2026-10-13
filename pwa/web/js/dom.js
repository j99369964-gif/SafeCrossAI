// Tiny DOM helper. Elements are built from text nodes and attributes only; nothing here ever parses HTML,
// so text from the server or the user can never become markup.
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(typeof child === "object" && child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

// "a **b** c" parts from the server -> text with <strong>, still without parsing HTML.
export function boldParts(parts) {
  return parts.map(([text, bold]) => (bold ? h("strong", {}, text) : text));
}
