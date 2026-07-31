(function () {
  const onReady = (fn) => {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  };

  const scheduleIdle = (fn) => {
    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(fn, { timeout: 10000 });
    } else {
      setTimeout(fn, 1200);
    }
  };

  onReady(() => {
    const setScrollOffset = () => {
      const header = document.querySelector(".site-header");
      if (!header) return;
      const height = header.getBoundingClientRect().height;
      const offset = Math.ceil(height + 16);
      document.documentElement.style.setProperty("--site-header-offset", `${offset}px`);
    };

    setScrollOffset();
    window.addEventListener("resize", setScrollOffset);

    const content = document.querySelector(".post-content");
    const readTimeEl = document.getElementById("postReadTime");
    const tocList = document.getElementById("postTocList");
    const crumbEl = document.getElementById("postTocCrumb");
    const toc = document.querySelector(".post-toc");
    const progressEl = document.getElementById("postTocProgress");
    const readingStatus = document.getElementById("readingStatus");
    const drawerToggle = document.getElementById("postTocDrawerToggle");
    const backdrop = document.getElementById("postTocBackdrop");

    if (!content) return;

    const configuredReadMinutes = Number.parseInt(
      readingStatus?.dataset.readMinutes || "",
      10
    );
    const readMinutes = Number.isFinite(configuredReadMinutes)
      ? Math.max(1, configuredReadMinutes)
      : 1;

    const updateReadingProgress = () => {
      const viewportHeight =
        window.innerHeight || document.documentElement.clientHeight || 0;
      const contentRect = content.getBoundingClientRect();
      const contentTop = window.scrollY + contentRect.top;
      const maxScroll = Math.max(1, content.offsetHeight - viewportHeight);
      const scrollY = window.scrollY - contentTop;
      const progress = Math.min(1, Math.max(0, scrollY / maxScroll));
      const percentage = Math.round(progress * 100);
      if (progressEl) {
        progressEl.style.width = `${(progress * 100).toFixed(2)}%`;
      }
      if (readingStatus) {
        const remaining = Math.max(0, Math.ceil(readMinutes * (1 - progress)));
        readingStatus.textContent = `${percentage}% · ${remaining} min left`;
      }
    };

    let readingProgressQueued = false;
    const queueReadingProgress = () => {
      if (readingProgressQueued) return;
      readingProgressQueued = true;
      window.requestAnimationFrame(() => {
        readingProgressQueued = false;
        updateReadingProgress();
      });
    };
    window.addEventListener("scroll", queueReadingProgress, { passive: true });
    window.addEventListener("resize", queueReadingProgress);
    window.addEventListener("load", queueReadingProgress);
    if ("ResizeObserver" in window) {
      new ResizeObserver(queueReadingProgress).observe(content);
    }
    queueReadingProgress();

    const setupAppletFrames = () => {
      const frames = Array.from(content.querySelectorAll("iframe.applet-frame"));
      if (frames.length === 0) return;

      const ensureEmbeddedStyling = (doc) => {
        if (!doc || !doc.documentElement) return;
        doc.documentElement.classList.add("is-embedded");
      };

      const queueResizeFrame = (frame) => {
        if (frame.dataset.appletResizeQueued === "true") return;
        frame.dataset.appletResizeQueued = "true";
        requestAnimationFrame(() => {
          frame.dataset.appletResizeQueued = "false";
          resizeFrame(frame);
        });
      };

      const resizeFrame = (frame) => {
        try {
          const doc = frame.contentDocument;
          if (!doc) return;
          ensureEmbeddedStyling(doc);
          const html = doc.documentElement;
          const body = doc.body;
          if (!html || !body) return;
          const measuredHeight = Math.max(
            html.scrollHeight,
            html.offsetHeight,
            body.scrollHeight,
            body.offsetHeight,
            Math.ceil(body.getBoundingClientRect().height)
          );
          if (!Number.isFinite(measuredHeight) || measuredHeight < 120) {
            return;
          }
          const useFullHeight = frame.getAttribute("data-applet-full-height") === "true";
          const rawMaxHeight = frame.getAttribute("data-applet-max-height");
          const parsedMaxHeight = rawMaxHeight ? Number.parseInt(rawMaxHeight, 10) : NaN;
          const hasMaxHeight = !useFullHeight && Number.isFinite(parsedMaxHeight) && parsedMaxHeight >= 120;
          const targetHeight = hasMaxHeight
            ? Math.min(Math.ceil(measuredHeight), parsedMaxHeight)
            : Math.ceil(measuredHeight);
          const previousHeight = Number.parseInt(frame.dataset.appletMeasuredHeight || "", 10);
          if (Number.isFinite(previousHeight) && Math.abs(previousHeight - targetHeight) < 2) {
            return;
          }
          frame.dataset.appletMeasuredHeight = `${targetHeight}`;
          frame.style.maxHeight = hasMaxHeight ? `${parsedMaxHeight}px` : "";
          frame.style.height = `${targetHeight}px`;
        } catch (err) {
          // Cross-origin frame; keep CSS fallback height.
          if (frame.getAttribute("data-applet-full-height") === "true") {
            frame.style.maxHeight = "";
            frame.style.height = "";
          }
        }
      };

      frames.forEach((frame) => {
        const onLoad = () => {
          queueResizeFrame(frame);
          setTimeout(() => queueResizeFrame(frame), 60);
          setTimeout(() => queueResizeFrame(frame), 260);
          if (frame.dataset.appletResizeHooksBound === "true") {
            return;
          }
          frame.dataset.appletResizeHooksBound = "true";
          try {
            const win = frame.contentWindow;
            if (win) {
              win.addEventListener("resize", () => queueResizeFrame(frame));
            }
            const doc = frame.contentDocument;
            if (doc && doc.body && "ResizeObserver" in window) {
              const observer = new ResizeObserver(() => queueResizeFrame(frame));
              observer.observe(doc.body);
              if (doc.documentElement) {
                observer.observe(doc.documentElement);
              }
            }
          } catch (err) {
            // Ignore sizing hooks when frame internals are inaccessible.
          }
        };
        frame.addEventListener("load", onLoad);
        if (frame.contentDocument?.readyState === "complete") {
          onLoad();
        }
      });

      content.querySelectorAll("[data-applet-shell]").forEach((shell) => {
        const frame = shell.querySelector("iframe.applet-frame");
        const reset = shell.querySelector("[data-applet-reset]");
        const fullscreen = shell.querySelector("[data-applet-fullscreen]");
        reset?.addEventListener("click", () => {
          if (frame) frame.src = frame.src;
        });
        fullscreen?.addEventListener("click", () => {
          if (shell.requestFullscreen) {
            shell.requestFullscreen().catch(() => {});
          }
        });
      });
    };

    setupAppletFrames();

    const anchorSlugCounts = new Map();
    const slugify = (text, prefix = "") => {
      const base = text
        .toLowerCase()
        .replace(/[^a-z0-9\\s-]/g, "")
        .trim()
        .replace(/\\s+/g, "-");
      const key = `${prefix}:${base}`;
      const count = anchorSlugCounts.get(key) || 0;
      anchorSlugCounts.set(key, count + 1);
      const suffix = count ? `-${count + 1}` : "";
      if (!base) {
        return `section-${anchorSlugCounts.size}`;
      }
      return `${base}${suffix}`;
    };

    const showCopyToast = (anchor, message = "Link copied") => {
      const toast = document.createElement("div");
      toast.className = "copy-toast";
      toast.textContent = message;
      document.body.appendChild(toast);
      const rect = anchor.getBoundingClientRect();
      const top = Math.max(12, rect.top - 28);
      const left = Math.max(12, Math.min(rect.left, window.innerWidth - 120));
      toast.style.top = `${top}px`;
      toast.style.left = `${left}px`;
      requestAnimationFrame(() => {
        toast.classList.add("is-visible");
      });
      setTimeout(() => {
        toast.classList.remove("is-visible");
        setTimeout(() => toast.remove(), 200);
      }, 1200);
    };

    content.querySelectorAll("[data-code-copy]").forEach((button) => {
      button.addEventListener("click", () => {
        const code = button.closest(".code-block")?.querySelector("code");
        const text = code?.textContent || "";
        navigator.clipboard?.writeText(text).catch(() => {});
        showCopyToast(button, "Code copied");
      });
    });

    document.querySelectorAll("[data-share-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        const url = button.dataset.shareUrl || window.location.href;
        if (navigator.share) {
          try {
            await navigator.share({ title: document.title, url });
            return;
          } catch (error) {
            if (error?.name === "AbortError") return;
          }
        }
        navigator.clipboard?.writeText(url).catch(() => {});
        showCopyToast(button, "Link copied");
      });
    });

    document.querySelectorAll("[data-cite-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const citation = button.dataset.citation || document.title;
        navigator.clipboard?.writeText(citation).catch(() => {});
        showCopyToast(button, "Citation copied");
      });
    });

    const addAnchor = (el, prefix, explicitId = "", textOverride = "") => {
      if (!el || el.querySelector(".para-anchor")) return;
      const rawText = textOverride || (el.textContent || "");
      const text = rawText.trim();
      if (!text && !explicitId && !el.id) return;
      let id = el.id || explicitId;
      if (!id) {
        const slugSource = text.split(/\\s+/).slice(0, 12).join(" ");
        const base = slugify(slugSource, prefix);
        id = prefix ? `${prefix}-${base}` : base;
      }
      el.id = id;
      const anchor = document.createElement("a");
      anchor.className = "para-anchor";
      anchor.href = `#${id}`;
      anchor.textContent = "";
      anchor.setAttribute("aria-label", `Copy link to ${text || "section"}`);
      anchor.addEventListener("click", () => {
        const url = `${window.location.origin}${window.location.pathname}#${id}`;
        navigator.clipboard?.writeText(url).catch(() => {});
        showCopyToast(anchor);
      });
      el.prepend(anchor);
    };

    content.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach((heading) => addAnchor(heading, "h"));

    const headings = Array.from(content.querySelectorAll("h1, h2, h3"));

    if (headings.length === 0) {
      if (toc) toc.style.display = "none";
      if (drawerToggle) drawerToggle.style.display = "none";
    } else if (tocList && crumbEl && toc) {
      const headingMeta = [];
      let currentH1 = "";
      let currentH1Id = "";
      let currentH2 = "";
      let currentH2Id = "";
      let firstH1Id = "";

      headings.forEach((heading) => {
        const text = heading.textContent.trim();
        if (!heading.id) {
          const base = slugify(text, "h");
          heading.id = `h-${base}`;
        }
        const level = heading.tagName.toLowerCase();
        if (level === "h1") {
          currentH1 = text;
          currentH1Id = heading.id;
          currentH2 = "";
          currentH2Id = "";
          if (!firstH1Id) firstH1Id = heading.id;
        }
        if (level === "h2") {
          currentH2 = text;
          currentH2Id = heading.id;
        }
        headingMeta.push({
          id: heading.id,
          text,
          level,
          parent: level === "h2" ? currentH1 : level === "h3" ? currentH2 : "",
          parentId: level === "h2" ? currentH1Id : level === "h3" ? currentH2Id : "",
          grandparentId: level === "h3" ? currentH1Id : "",
        });
      });

      let itemRefs = [];

      const hasH1 = headingMeta.some((entry) => entry.level === "h1");
      const hasStaticToc = tocList.children.length > 0;

      if (!hasStaticToc) {
        headingMeta.forEach((meta) => {
          const li = document.createElement("li");
          li.className = "post-toc__item";
          li.classList.add(`post-toc__item--${meta.level}`);
          li.dataset.level = meta.level;
          itemRefs.push(li);

          const link = document.createElement("a");
          link.className = "post-toc__link";
          link.href = `#${meta.id}`;
          link.textContent = meta.text || meta.id;
          link.dataset.tocId = meta.id;
          if (meta.parentId) {
            link.dataset.parentId = meta.parentId;
          }
          if (meta.grandparentId) {
            link.dataset.grandparentId = meta.grandparentId;
          }
          li.appendChild(link);
          tocList.appendChild(li);
        });
        itemRefs = Array.from(tocList.querySelectorAll(".post-toc__item"));
      } else {
        itemRefs = Array.from(tocList.querySelectorAll(".post-toc__item"));
        itemRefs.forEach((item) => {
          if (item.dataset.level) return;
          if (item.classList.contains("post-toc__item--h1")) item.dataset.level = "h1";
          else if (item.classList.contains("post-toc__item--h2")) item.dataset.level = "h2";
          else if (item.classList.contains("post-toc__item--h3")) item.dataset.level = "h3";
        });
        tocList.querySelectorAll(".post-toc__link").forEach((link) => {
          if (!link.dataset.tocId) {
            const href = link.getAttribute("href") || "";
            if (href.startsWith("#")) link.dataset.tocId = href.slice(1);
          }
        });
      }

      const links = Array.from(tocList.querySelectorAll(".post-toc__link"));

      if (headings.length <= 2) {
        toc.classList.add("post-toc--compact");
      }

      const setScrollbarOffset = (value) => {
        document.documentElement.style.setProperty("--scrollbar-offset", value);
      };

      const openDrawer = () => {
        const scrollBarWidth = Math.max(
          0,
          window.innerWidth - document.documentElement.clientWidth
        );
        setScrollbarOffset(`${scrollBarWidth}px`);
        document.body.classList.add("toc-drawer-open");
        if (drawerToggle) drawerToggle.setAttribute("aria-expanded", "true");
      };

      const closeDrawer = () => {
        document.body.classList.remove("toc-drawer-open");
        setScrollbarOffset("0px");
        if (drawerToggle) drawerToggle.setAttribute("aria-expanded", "false");
      };

      if (drawerToggle) {
        drawerToggle.addEventListener("click", () => {
          if (document.body.classList.contains("toc-drawer-open")) {
            closeDrawer();
          } else {
            openDrawer();
          }
        });
      }

      if (backdrop) {
        backdrop.addEventListener("click", closeDrawer);
      }

      window.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeDrawer();
      });

      const updateActive = (id) => {
        let activeH1Id = firstH1Id;
        let activeH2Id = "";
        links.forEach((link) => {
          const isActive = link.dataset.tocId === id;
          link.classList.toggle("is-active", isActive);
          const item = link.closest(".post-toc__item");
          if (item) item.classList.toggle("is-active", isActive);
        });
        const meta = headingMeta.find((entry) => entry.id === id);
        if (!meta) return;
        if (meta.level === "h1") {
          crumbEl.textContent = meta.text;
          activeH1Id = meta.id;
          activeH2Id = "";
        } else if (meta.level === "h2") {
          crumbEl.textContent = meta.parent ? `${meta.parent} → ${meta.text}` : meta.text;
          activeH1Id = meta.parentId;
          activeH2Id = meta.id;
        } else {
          crumbEl.textContent = meta.parent ? `${meta.parent} → ${meta.text}` : meta.text;
          activeH1Id = meta.grandparentId || meta.parentId || firstH1Id;
          activeH2Id = meta.parentId;
        }

        itemRefs.forEach((item) => {
          const level = item.dataset.level;
          if (level === "h1") {
            item.classList.remove("is-hidden");
            return;
          }
          if (level === "h2") {
            const parentId = item.querySelector(".post-toc__link")?.dataset.parentId;
            if (hasH1) {
              item.classList.toggle("is-hidden", parentId !== activeH1Id);
            } else {
              item.classList.remove("is-hidden");
            }
            return;
          }
          if (level === "h3") {
            const parentId = item.querySelector(".post-toc__link")?.dataset.parentId;
            item.classList.toggle("is-hidden", parentId !== activeH2Id);
          }
        });
      };

      let ticking = false;
      let recomputeQueued = false;
      let headingPositions = [];

      const updateProgress = () => {
        updateReadingProgress();
      };

      const isHeadingVisible = (heading) => {
        if (!heading) return false;
        if (heading.closest("details:not([open])")) return false;
        if (heading.offsetParent === null) return false;
        if (heading.getClientRects().length === 0) return false;
        return true;
      };

      const recomputeLayoutMetrics = () => {
        headingPositions = [];
        headings.forEach((heading) => {
          if (!isHeadingVisible(heading)) return;
          headingPositions.push({ id: heading.id, top: heading.offsetTop });
        });
      };

      const findActiveHeadingId = (fromTop) => {
        if (headingPositions.length === 0) {
          return headings[0]?.id || "";
        }
        let low = 0;
        let high = headingPositions.length - 1;
        let currentId = headingPositions[0].id;
        while (low <= high) {
          const mid = (low + high) >> 1;
          const entry = headingPositions[mid];
          if (entry.top <= fromTop) {
            currentId = entry.id;
            low = mid + 1;
          } else {
            high = mid - 1;
          }
        }
        return currentId;
      };

      const onScroll = () => {
        if (ticking) return;
        ticking = true;
        window.requestAnimationFrame(() => {
          const fromTop = window.scrollY + 140;
          const activeId = findActiveHeadingId(fromTop);
          if (activeId) updateActive(activeId);
          updateProgress();
          ticking = false;
        });
      };

      const queueRecompute = () => {
        if (recomputeQueued) return;
        recomputeQueued = true;
        window.requestAnimationFrame(() => {
          recomputeQueued = false;
          recomputeLayoutMetrics();
          onScroll();
        });
      };

      window.addEventListener("scroll", onScroll, { passive: true });
      window.addEventListener("load", queueRecompute);
      const resizeObserver = "ResizeObserver" in window ? new ResizeObserver(queueRecompute) : null;
      if (resizeObserver) resizeObserver.observe(content);
      content.querySelectorAll("details.collapsible-block").forEach((details) => {
        details.addEventListener("toggle", queueRecompute);
      });
      const handleResize = () => {
        queueRecompute();
        if (window.matchMedia("(min-width: 1100px)").matches) {
          closeDrawer();
        }
      };

      window.addEventListener("resize", handleResize);
      queueRecompute();

      links.forEach((link) => {
        link.addEventListener("click", closeDrawer);
      });
    }

    scheduleIdle(() => {
      const needsClientReadTimePass = (() => {
        if (!readTimeEl) return false;
        const mainText = readTimeEl.querySelector(".post-readtime__main")?.textContent || "";
        const deepText = readTimeEl.querySelector(".post-readtime__deep")?.textContent || "";
        if (mainText.includes("-- min") || deepText.includes("-- min")) return true;
        return Array.from(content.querySelectorAll("[data-collapsible-readtime]")).some((label) =>
          (label.textContent || "").includes("-- min")
        );
      })();

      if (needsClientReadTimePass) {
        const wordRegex = /[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?/g;
        const countWordsInString = (text) => (text.match(wordRegex) || []).length;
        const mathCharsPerWord = 8;
        const wordsPerMinute = 220;

        const countMathWords = (el) => {
          const annotations = el.querySelectorAll("annotation[encoding='application/x-tex']");
          let tex = "";
          annotations.forEach((node) => {
            if (node.textContent) tex += ` ${node.textContent}`;
          });
          if (!tex) {
            tex = el.textContent || "";
          }
          const compact = tex.replace(/\\s+/g, "");
          if (!compact) return 0;
          return Math.max(1, Math.ceil(compact.length / mathCharsPerWord));
        };

        const countTableWords = (table) => {
          let total = 0;
          table.querySelectorAll("th, td").forEach((cell) => {
            const text = (cell.textContent || "").trim();
            const words = countWordsInString(text);
            if (words === 0 && text.length > 0) {
              total += 1;
            } else {
              total += words;
            }
          });
          return total;
        };

        const shouldSkip = (el) =>
          el.matches("script, style, nav") ||
          el.classList.contains("para-anchor") ||
          el.classList.contains("post-toc") ||
          el.classList.contains("post-sidebar") ||
          el.classList.contains("glossary-data") ||
          el.classList.contains("glossary-tooltip") ||
          el.classList.contains("collapsible-block__readtime") ||
          el.classList.contains("collapsible-block__icon") ||
          el.classList.contains("copy-toast");

        const collapsibleCounts = new Map();

        const countNode = (node) => {
          if (!node) return { main: 0, deep: 0 };
          if (node.nodeType === Node.TEXT_NODE) {
            const words = countWordsInString(node.textContent || "");
            return { main: words, deep: words };
          }
          if (node.nodeType !== Node.ELEMENT_NODE) {
            return { main: 0, deep: 0 };
          }

          const el = node;
          if (shouldSkip(el)) {
            return { main: 0, deep: 0 };
          }

          if (
            el.classList.contains("katex") ||
            el.classList.contains("katex-display") ||
            el.classList.contains("latex-block")
          ) {
            const words = countMathWords(el);
            return { main: words, deep: words };
          }

          if (el.tagName === "TABLE") {
            const words = countTableWords(el);
            return { main: words, deep: words };
          }

          if (el.tagName === "DETAILS" && el.classList.contains("collapsible-block")) {
            const summary = el.querySelector(":scope > summary");
            const contentEl = el.querySelector(":scope > .collapsible-block__content");
            const summaryCounts = summary ? countNode(summary) : { main: 0, deep: 0 };
            const contentCounts = contentEl ? countNode(contentEl) : { main: 0, deep: 0 };
            const isOpen = el.hasAttribute("open");
            const main = summaryCounts.main + (isOpen ? contentCounts.deep : 0);
            const deep = summaryCounts.deep + contentCounts.deep;
            if (contentEl) {
              collapsibleCounts.set(el, contentCounts.deep);
            }
            return { main, deep };
          }

          let main = 0;
          let deep = 0;
          el.childNodes.forEach((child) => {
            const counts = countNode(child);
            main += counts.main;
            deep += counts.deep;
          });
          return { main, deep };
        };

        const formatMinutes = (words) => {
          const minutes = Math.max(1, Math.round(words / wordsPerMinute));
          return `${minutes} min`;
        };

        const counts = countNode(content);
        const mainEl = readTimeEl.querySelector(".post-readtime__main");
        const deepEl = readTimeEl.querySelector(".post-readtime__deep");
        if (mainEl) mainEl.textContent = `Main path: ${formatMinutes(counts.main)}`;
        if (deepEl) deepEl.textContent = `With deep dives: ${formatMinutes(counts.deep)}`;

        if (collapsibleCounts.size > 0) {
          content.querySelectorAll(".collapsible-block__summary").forEach((summary) => {
            const details = summary.closest("details");
            if (!details) return;
            const label = summary.querySelector("[data-collapsible-readtime]");
            const words = collapsibleCounts.get(details);
            if (label && typeof words === "number") {
              label.textContent = formatMinutes(words);
            }
          });
        }
      }

      const glossaryTerms = new Map();
      const glossaryBlocks = content.querySelectorAll(".glossary-data");
      glossaryBlocks.forEach((block) => {
        block.querySelectorAll(".glossary-data__entry").forEach((entry) => {
          const term = (entry.dataset.term || "").trim();
          const definition = (entry.dataset.definition || "").trim();
          if (!term || !definition) return;
          const aliases = (entry.dataset.aliases || "")
            .split(",")
            .map((alias) => alias.trim())
            .filter(Boolean);
          const key = term.toLowerCase();
          glossaryTerms.set(key, { term, definition });
          aliases.forEach((alias) => {
            const aliasKey = alias.toLowerCase();
            if (!glossaryTerms.has(aliasKey)) {
              glossaryTerms.set(aliasKey, { term, definition });
            }
          });
        });
      });

      const bindGlossaryTerms = () => {
        if (glossaryTerms.size === 0) return;
        const glossaryButtons = Array.from(content.querySelectorAll(".glossary-term"));
        if (glossaryButtons.length === 0) return;

        const tooltip = document.createElement("div");
        tooltip.className = "glossary-tooltip";
        tooltip.setAttribute("role", "tooltip");
        tooltip.innerHTML = `
          <div class="glossary-tooltip__term"></div>
          <div class="glossary-tooltip__def"></div>
        `;
        document.body.appendChild(tooltip);

        const termEl = tooltip.querySelector(".glossary-tooltip__term");
        const defEl = tooltip.querySelector(".glossary-tooltip__def");
        const normalizeLatexInput = (input) =>
          input
            .replace(/[\u2018\u2019]/g, "'")
            .replace(/[\u201c\u201d]/g, '"');
        const katexOptions = {
          delimiters: [
            { left: "[latex]", right: "[/latex]", display: true },
            { left: "$$", right: "$$", display: true },
            { left: "\\[", right: "\\]", display: true },
            { left: "\\(", right: "\\)", display: false },
            { left: "$", right: "$", display: false },
          ],
          throwOnError: false,
          preProcess: normalizeLatexInput,
        };

        let activeTarget = null;

        const positionTooltip = (target) => {
          const rect = target.getBoundingClientRect();
          const tooltipRect = tooltip.getBoundingClientRect();
          const spacing = 10;
          let top = rect.top - tooltipRect.height - spacing;
          if (top < 8) {
            top = rect.bottom + spacing;
          }
          let left = rect.left + rect.width / 2 - tooltipRect.width / 2;
          left = Math.max(8, Math.min(left, window.innerWidth - tooltipRect.width - 8));
          tooltip.style.top = `${top}px`;
          tooltip.style.left = `${left}px`;
        };

        const showTooltip = (target) => {
          const key = (target.dataset.termKey || "").toLowerCase();
          const data = glossaryTerms.get(key);
          if (!data) return;
          if (termEl) termEl.textContent = data.term;
          if (defEl) {
            defEl.textContent = data.definition;
            if (window.renderMathInElement) {
              window.renderMathInElement(defEl, katexOptions);
            }
          }
          tooltip.classList.add("is-visible");
          positionTooltip(target);
          activeTarget = target;
        };

        const hideTooltip = () => {
          tooltip.classList.remove("is-visible");
          activeTarget = null;
        };

        const wireGlossaryButton = (button) => {
          if (!button || button.dataset.glossaryWired === "true") return;
          button.dataset.glossaryWired = "true";
          if (button.hasAttribute("title")) {
            button.dataset.nativeTitle = button.getAttribute("title") || "";
            button.removeAttribute("title");
          }
          let lastPointerType = null;
          button.addEventListener("mouseenter", () => showTooltip(button));
          button.addEventListener("mouseleave", hideTooltip);
          button.addEventListener("focus", () => showTooltip(button));
          button.addEventListener("blur", hideTooltip);
          button.addEventListener("pointerdown", (event) => {
            lastPointerType = event.pointerType || "mouse";
          });
          button.addEventListener(
            "touchstart",
            () => {
              lastPointerType = "touch";
            },
            { passive: true }
          );
          button.addEventListener("click", (event) => {
            event.stopPropagation();
            const pointerType = lastPointerType;
            lastPointerType = null;
            if (pointerType === "touch") {
              showTooltip(button);
              return;
            }
            if (activeTarget === button) {
              hideTooltip();
            } else {
              showTooltip(button);
            }
          });
        };

        glossaryButtons.forEach((button) => {
          if (!button.dataset.termKey) {
            const key = (button.textContent || "").trim().toLowerCase();
            if (glossaryTerms.has(key)) {
              button.dataset.termKey = key;
            }
          }
          if (button.dataset.termKey) {
            wireGlossaryButton(button);
          }
        });

        document.addEventListener(
          "scroll",
          () => {
            if (activeTarget) positionTooltip(activeTarget);
          },
          { passive: true }
        );

        document.addEventListener("click", (event) => {
          if (!activeTarget) return;
          if (event.target.closest(".glossary-tooltip") || event.target.closest(".glossary-term")) {
            return;
          }
          hideTooltip();
        });
      };

      bindGlossaryTerms();
    });
  });
})();
