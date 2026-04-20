(function () {
  const Monitor = window.Monitor;
  const STORAGE_KEY = "silver-monitor-section-order";

  /**
   * 初始化拖拽排序功能
   * 使用 HTML5 Drag & Drop API，各 .drag-section 可通过 .drag-handle 拖拽
   * 顺序持久化到 localStorage
   */
  Monitor.initDragSort = function () {
    document.querySelectorAll(".sortable-container").forEach(initContainer);
  };

  function initContainer(container) {
    const containerId = container.id || "default";
    let draggedEl = null;

    // 恢复保存的顺序
    restoreOrder(container, containerId);

    container.querySelectorAll(".drag-section").forEach(section => {
      section.setAttribute("draggable", "true");

      section.addEventListener("dragstart", function (e) {
        // 只允许从 drag-handle 开始拖拽
        if (!e.target.closest(".drag-handle") && e.target !== section) {
          // 检查是否点击了 handle
          const handle = section.querySelector(".drag-handle");
          const rect = handle.getBoundingClientRect();
          if (e.clientX < rect.left || e.clientX > rect.right ||
              e.clientY < rect.top || e.clientY > rect.bottom) {
            e.preventDefault();
            return;
          }
        }
        draggedEl = section;
        section.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", section.dataset.section);
      });

      section.addEventListener("dragend", function () {
        section.classList.remove("dragging");
        container.querySelectorAll(".drag-section").forEach(s => s.classList.remove("drag-over"));
        draggedEl = null;
        saveOrder(container, containerId);
        // 刷新图表尺寸（移动后 canvas 可能需要重绘）
        if (Monitor.resizeVisibleCharts) {
          setTimeout(Monitor.resizeVisibleCharts, 100);
        }
      });

      section.addEventListener("dragover", function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (!draggedEl || draggedEl === section) return;

        const rect = section.getBoundingClientRect();
        const midY = rect.top + rect.height / 2;

        container.querySelectorAll(".drag-section").forEach(s => s.classList.remove("drag-over"));
        section.classList.add("drag-over");

        if (e.clientY < midY) {
          container.insertBefore(draggedEl, section);
        } else {
          container.insertBefore(draggedEl, section.nextSibling);
        }
      });

      section.addEventListener("dragleave", function () {
        section.classList.remove("drag-over");
      });

      section.addEventListener("drop", function (e) {
        e.preventDefault();
        section.classList.remove("drag-over");
      });

      // 让 handle 区域显示拖拽手型
      const handle = section.querySelector(".drag-handle");
      if (handle) {
        handle.addEventListener("mousedown", function () {
          section.setAttribute("draggable", "true");
        });
      }
    });
  }

  function saveOrder(container, containerId) {
    const order = [];
    container.querySelectorAll(".drag-section").forEach(s => {
      if (s.dataset.section) order.push(s.dataset.section);
    });
    try {
      const all = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      all[containerId] = order;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
    } catch (_) {}
  }

  function restoreOrder(container, containerId) {
    try {
      const all = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      const order = all[containerId];
      if (!Array.isArray(order) || order.length === 0) return;

      const sectionMap = {};
      container.querySelectorAll(".drag-section").forEach(s => {
        if (s.dataset.section) sectionMap[s.dataset.section] = s;
      });

      // 按保存的顺序重排
      order.forEach(key => {
        if (sectionMap[key]) {
          container.appendChild(sectionMap[key]);
        }
      });
    } catch (_) {}
  }

  // 页面加载后初始化
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", Monitor.initDragSort);
  } else {
    Monitor.initDragSort();
  }
})();
