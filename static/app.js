// 全局共享 JS：HTML 转义、通知提示条、主题初始化与切换。
// 由 templates/base.html 引入，且先于各页面内联脚本加载，确保共享函数全局可用。

// HTML 转义：防止文件名等用户输入直接注入 innerHTML
function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// 顶部通知提示条：供各页面内联脚本调用
function showNotification(message, type = "success") {
  const notification = document.getElementById("notification");
  const notificationMessage = document.getElementById(
    "notificationMessage"
  );
  notification.className = "notification";
  notification.classList.add(type);
  notificationMessage.textContent = message;
  notification.style.display = "flex"; // 显示通知
  setTimeout(() => {
    notification.style.display = "none"; // 3秒后隐藏
  }, 3000);
}

// 主题初始化与切换：localStorage 记忆 + 跟随系统偏好
function initTheme() {
  const themeToggle = document.getElementById("themeToggle");
  if (!themeToggle) {
    return;
  }
  const savedTheme = localStorage.getItem("theme");
  const prefersDarkScheme = window.matchMedia(
    "(prefers-color-scheme: dark)"
  ).matches;
  if (
    savedTheme === "dark" ||
    (savedTheme === null && prefersDarkScheme)
  ) {
    document.documentElement.setAttribute("data-theme", "dark");
    themeToggle.checked = true;
  } else {
    document.documentElement.setAttribute("data-theme", "light");
    themeToggle.checked = false;
  }
  themeToggle.addEventListener("change", function () {
    if (this.checked) {
      document.documentElement.setAttribute("data-theme", "dark");
      localStorage.setItem("theme", "dark");
      showNotification("已切换到深色主题", "success");
    } else {
      document.documentElement.setAttribute("data-theme", "light");
      localStorage.setItem("theme", "light");
      showNotification("已切换到浅色主题", "success");
    }
  });
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", (e) => {
      if (!localStorage.getItem("theme")) {
        const newTheme = e.matches ? "dark" : "light";
        document.documentElement.setAttribute("data-theme", newTheme);
        themeToggle.checked = e.matches;
        showNotification(
          `已根据系统设置切换到${e.matches ? "深色" : "浅色"}主题`,
          "success"
        );
      }
    });
}

document.addEventListener("DOMContentLoaded", function () {
  initTheme();
});
