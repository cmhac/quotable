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

  get children() {
    return this.childNodes.filter((c) => c.nodeType === 1);
  }
}

export function installDom() {
  globalThis.document = {
    createElement: (tag) => new FakeElement(tag),
    createTextNode: (data) => new FakeText(data),
  };
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
