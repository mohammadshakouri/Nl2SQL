// frontend/node_modules/lestin/jsx-runtime/dist/jsx-runtime.mjs
var namespaces = {
  svg: "http://www.w3.org/2000/svg",
  html: "http://www.w3.org/1999/xhtml",
  xml: "http://www.w3.org/XML/1998/namespace",
  xlink: "http://www.w3.org/1999/xlink",
  xmlns: "http://www.w3.org/2000/xmlns/",
  mathMl: "http://www.w3.org/1998/Math/MathML"
};
var svgElements = [
  // "a",
  "animate",
  "animateMotion",
  "animateTransform",
  "circle",
  "clipPath",
  "defs",
  "desc",
  "discard",
  "ellipse",
  // "feBlend",
  // "feColorMatrix",
  // "feComponentTransfer",
  // "feComposite",
  // "feConvolveMatrix",
  // "feDiffuseLighting",
  // "feDisplacementMap",
  // "feDistantLight",
  // "feDropShadow",
  // "feFlood",
  // "feFuncA",
  // "feFuncB",
  // "feFuncG",
  // "feFuncR",
  // "feGaussianBlur",
  // "feImage",
  // "feMerge",
  // "feMergeNode",
  // "feMorphology",
  // "feOffset",
  // "fePointLight",
  // "feSpecularLighting",
  // "feSpotLight",
  // "feTile",
  // "feTurbulence",
  "filter",
  "foreignObject",
  "g",
  "image",
  "line",
  "linearGradient",
  "marker",
  "mask",
  "metadata",
  "mpath",
  "path",
  "pattern",
  "polygon",
  "polyline",
  "radialGradient",
  "rect",
  // "script",
  "set",
  "stop",
  // "style",
  "svg",
  "switch",
  "symbol",
  "text",
  "textPath",
  // "title",
  "tspan",
  "use",
  "view"
];
function CreateElement(type, props = {}) {
  let { children, ...attrs } = props;
  if (!Array.isArray(children)) {
    children = [children];
  }
  let childrenLength = children.length;
  for (let i = 0; i < childrenLength; i++) {
    const child = children[i];
    if (!(Boolean(child) && !(Array.isArray(child) && !child.length) || child === 0)) {
      children.splice(i, 1);
    }
  }
  childrenLength = children.length;
  props.children = children;
  if (typeof type === "function") {
    return type(props);
  }
  if (svgElements.includes(type)) {
    attrs.xmlns = namespaces.svg;
  }
  let element;
  if (attrs.xmlns) {
    element = document.createElementNS(attrs.xmlns, type);
  } else {
    element = document.createElement(type);
  }
  for (const propName in attrs) {
    if (!Object.hasOwn(attrs, propName)) {
      continue;
    }
    let propValue = attrs[propName];
    if (!propName || !propValue && typeof propValue !== "number" && propValue !== "") {
      continue;
    }
    if (propName === "__source" || propName === "__self" || propName === "tsxTag") {
      continue;
    }
    if (propName == "class" || propName == "className") {
      let className = "";
      if (Array.isArray(propValue)) {
        propValue = propValue.flat(5);
        const arrayLength = propValue.length;
        for (let i = 0; i < arrayLength; i++) {
          if (propValue[i]) {
            className += (className ? " " : "") + propValue[i].trim();
          }
        }
        propValue = className;
      }
      element.className = propValue;
    } else if (propName.startsWith("on")) {
      const finalName = propName.replace(/Capture$/, "");
      const useCapture = propName !== finalName;
      let eventName = finalName.toLowerCase().substring(2);
      if (eventName === "doubleclick") {
        eventName = "dblclick";
      }
      if (!Array.isArray(propValue)) {
        propValue = [propValue];
      }
      const arrayLength = propValue.length;
      for (let i = 0; i < arrayLength; i++) {
        if (eventName && propValue[i]) {
          element.addEventListener(eventName, propValue[i], useCapture);
        }
      }
    } else if (propName === "style") {
      if (typeof propValue === "string") {
        element.style.cssText = propValue;
      } else {
        Object.assign(element.style, propValue);
      }
    } else if (propName === "dataset") {
      Object.assign(element.dataset, propValue);
    } else if (propName == "htmlFor" || propName == "for") {
      element.htmlFor = propValue;
    } else if (["innerHTML", "innerText", "textContent"].includes(propName)) {
      element[propName] = propValue;
    } else if (propName === "ref") {
      propValue.current = element;
    } else if (propName === "assign" && typeof propValue === "function") {
      propValue(element);
    } else if (propName === "xmlns") {
      element.setAttributeNS(namespaces.xmlns, propName, propValue.toString());
    } else {
      if (propValue === true) {
        propValue = propName;
      }
      element.setAttribute(propName, propValue.toString());
    }
  }
  for (let i = 0; i < childrenLength; i++) {
    const child = children[i];
    AppendChild(element, child);
  }
  return element;
}
var Fragment = (props) => props.children;
function AppendChild(parent, childOrText) {
  if (Array.isArray(childOrText)) {
    const childOrTextArrayLength = childOrText.length;
    for (let i = 0; i < childOrTextArrayLength; i++) {
      const nestedChild = childOrText[i];
      AppendChild(parent, nestedChild);
    }
  } else {
    const isElement = childOrText instanceof Element;
    parent.appendChild(isElement ? childOrText : document.createTextNode(childOrText));
  }
}
var createRef = (initialValue) => ({ current: initialValue });
export {
  AppendChild,
  CreateElement,
  Fragment,
  createRef,
  CreateElement as jsx,
  CreateElement as jsxDEV,
  CreateElement as jsxs
};
//# sourceMappingURL=lestin_jsx-runtime.js.map
