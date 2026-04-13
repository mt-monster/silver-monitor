(function () {
  const Monitor = window.Monitor;

  function getNode(id) {
    return Monitor.el(id);
  }

  function setText(id, value) {
    const node = getNode(id);
    if (node) node.textContent = value;
    return node;
  }

  function setHtml(id, value) {
    const node = getNode(id);
    if (node) node.innerHTML = value;
    return node;
  }

  function setClassName(id, value) {
    const node = getNode(id);
    if (node) node.className = value;
    return node;
  }

  function setStyle(id, property, value) {
    const node = getNode(id);
    if (node) node.style[property] = value;
    return node;
  }

  function toggleClass(id, className, enabled) {
    const node = getNode(id);
    if (node) node.classList.toggle(className, enabled);
    return node;
  }

  Monitor.dom = {
    getNode,
    setText,
    setHtml,
    setClassName,
    setStyle,
    toggleClass,
  };
})();
