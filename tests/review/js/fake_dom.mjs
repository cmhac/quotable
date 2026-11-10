// A just-enough DOM for the node tests of the app's pure functions and views.

class FakeNode {
  constructor() {
    this.childNodes = [];
  }

  appendChild(child) {
    this.childNodes.push(child);
    return child;
  }

  replaceChildren(...nodes) {
    this.childNodes = [];
    for (const node of nodes)
      this.appendChild(typeof node === "string" ? new FakeText(node) : node);
  }
}

class FakeText extends FakeNode {
  constructor(data) {
    super();
    this.nodeType = 3;
    this.data = String(data);
  }

  get textContent() {
    return this.data;
  }
}

class FakeElement extends FakeNode {
  constructor(tag) {
    super();
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.attributes = {};
    this.listeners = {};
    this.styles = {};
    this.style = { setProperty: (name, value) => (this.styles[name] = value) };
    this.dataset = {};
    this.hidden = false;
    this.classList = {
      toggle: (name, on) => {
        const names = new Set((this.attributes.class ?? "").split(" ").filter(Boolean));
        if (on ?? !names.has(name)) names.add(name);
        else names.delete(name);
        this.attributes.class = [...names].join(" ");
      },
      add: (name) => this.classList.toggle(name, true),
      remove: (name) => this.classList.toggle(name, false),
      contains: (name) => (this.attributes.class ?? "").split(" ").includes(name),
    };
  }

  // The gold entry screen's smoke test needs these; they do nothing a test looks at.
  append(...nodes) {
    for (const node of nodes)
      this.appendChild(typeof node === "string" ? new FakeText(node) : node);
  }

  removeEventListener(type, listener) {
    this.listeners[type] = (this.listeners[type] ?? []).filter((l) => l !== listener);
  }

  get lastChild() {
    return this.childNodes.at(-1);
  }

  querySelector() {
    return null;
  }

  querySelectorAll() {
    return [];
  }

  closest() {
    return null;
  }

  matches() {
    return false;
  }

  contains() {
    return false;
  }

  focus() {}

  blur() {}

  scrollIntoView() {}

  getBoundingClientRect() {
    return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  removeAttribute(name) {
    delete this.attributes[name];
  }

  getAttribute(name) {
    return this.attributes[name] ?? null;
  }

  addEventListener(type, listener) {
    (this.listeners[type] ??= []).push(listener);
  }

  get textContent() {
    return this.childNodes.map((c) => c.textContent).join("");
  }

  set textContent(value) {
    this.childNodes = [new FakeText(value)];
  }

  get children() {
    return this.childNodes.filter((c) => c.nodeType === 1);
  }
}

export function installDom() {
  globalThis.document = {
    createElement: (tag) => new FakeElement(tag),
    createElementNS: (_ns, tag) => new FakeElement(tag),
    createTextNode: (data) => new FakeText(data),
  };
}

// More of a browser, for a screen that wires document and window listeners.
export function installBrowser() {
  installDom();
  const listeners = {};
  const target = {
    listeners,
    addEventListener: (type, fn) => (listeners[type] ??= []).push(fn),
    removeEventListener: (type, fn) => {
      listeners[type] = (listeners[type] ?? []).filter((l) => l !== fn);
    },
  };
  Object.assign(globalThis.document, target, {
    hidden: false,
    activeElement: null,
    hasFocus: () => true,
  });
  globalThis.window = {
    ...target,
    listeners: {},
    getSelection: () => ({ rangeCount: 0, removeAllRanges() {}, toString: () => "" }),
  };
  const windowListeners = {};
  globalThis.window.addEventListener = (type, fn) => (windowListeners[type] ??= []).push(fn);
  globalThis.window.removeEventListener = (type, fn) => {
    windowListeners[type] = (windowListeners[type] ?? []).filter((l) => l !== fn);
  };
  globalThis.window.listeners = windowListeners;
  globalThis.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  globalThis.confirm = () => true;
}

export function findAll(node, predicate, found = []) {
  for (const child of node.childNodes ?? []) {
    if (child.nodeType === 1) {
      if (predicate(child)) found.push(child);
      findAll(child, predicate, found);
    }
  }
  return found;
}

export const byTag = (node, tag) =>
  findAll(node, (e) => e.tagName === tag.toUpperCase());
export const byClass = (node, name) =>
  findAll(node, (e) => (e.attributes.class ?? "").split(" ").includes(name));
