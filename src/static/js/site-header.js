(function () {
  const header = document.querySelector(".site-header");
  if (!header) return;

  const setScrollOffset = () => {
    const offset = Math.ceil(header.getBoundingClientRect().height + 16);
    document.documentElement.style.setProperty("--site-header-offset", `${offset}px`);
  };

  setScrollOffset();
  if ("ResizeObserver" in window) {
    new ResizeObserver(setScrollOffset).observe(header);
  } else {
    window.addEventListener("resize", setScrollOffset);
  }
})();
