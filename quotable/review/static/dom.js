// The only way the app builds DOM: strings are text nodes, never markup.

const OWN_PAGES = /^(#|\/(?!\/))/;

export function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  let value;
  for (const [name, given] of Object.entries(attrs ?? {})) {
    if (name === "value") value = given;
    else setAttribute(node, name, given);
  }
  append(node, children);
  if (value !== undefined && value !== null) node.value = value;
  return node;
}

function setAttribute(node, name, given) {
  if (given === null || given === undefined || given === false) return;
  if (name === "style") {
    for (const [property, text] of Object.entries(given))
      node.style.setProperty(property, String(text));
  } else if (name.startsWith("on") && typeof given === "function") {
    node.addEventListener(name.slice(2), given);
  } else if ((name === "href" || name === "src") && !OWN_PAGES.test(given)) {
    throw new Error(`unsafe ${name}: ${given}`);
  } else {
    node.setAttribute(name, given === true ? "" : String(given));
  }
}

function append(node, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) append(node, child);
    else if (typeof child === "object" && child.nodeType)
      node.appendChild(child);
    else node.appendChild(document.createTextNode(String(child)));
  }
}
