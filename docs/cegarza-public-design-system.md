# cegarza.com public design system

The public site uses the **Night Observatory** visual direction: an editorial
notebook viewed through the language of plots, coordinates, and instrument
panels. It is deliberately quieter than a product dashboard. Typography and
reading rhythm carry the content; orchid, ember, and cyan behave as small
signals rather than decoration spread across every surface.

## Principles

1. **The essay is the interface.** Article copy stays near a 70-character
   measure, uses generous leading, and gives headings enough space to act as
   navigation landmarks.
2. **Technical without looking like a terminal.** Display text uses the
   platform serif stack. Monospace is reserved for metadata, coordinates, code,
   and compact navigation labels.
3. **Signal, not glow.** Orchid is the brand signal, ember marks interruption or
   emphasis, and cyan is a rare supporting datum. Effects never reduce text
   contrast.
4. **Content imagery is evidence.** Featured images receive consistent crops on
   indexes and keep their intrinsic proportions in articles. Diagrams, tables,
   code, applets, and captions remain part of the reading column rather than
   being forced into decorative card treatments.
5. **Motion explains state.** The masthead signal points pulse gently and cards
   lift on hover. All nonessential motion is removed by
   `prefers-reduced-motion`.

## Tokens

The canonical tokens live at the top of `src/static/css/site.css`.

| Group | Contract |
| --- | --- |
| Canvas | `--ink-1000` through `--ink-800` |
| Copy | `--paper-50`, `--paper-100`, `--paper-300`, `--paper-500` |
| Signals | `--orchid-*`, `--ember-300`, `--cyan-300` |
| Semantics | `--surface-*`, `--text-*`, `--rule*` |
| Type | `--font-display`, `--font-body`, `--font-code`, `--measure-reading` |
| Rhythm | `--space-1` through `--space-8`, `--radius-*` |

Legacy `--color-*` aliases remain intentionally mapped to the new semantic
tokens. Imported Wagtail blocks and the embedded applets rely on those names,
so this keeps content rendering stable while the public shell evolves.

## Reusable template primitives

- `.eyebrow`, `.story-meta`, and `.story-tags` describe editorial metadata.
- `.button-primary`, `.text-link`, and `.story-link` cover interactive emphasis.
- `.site-title`, `.site-nav`, and `.site-footer` form the shared shell.
- `.home-hero`, `.section-heading`, `.lead-story`, and `.post-card` form index
  compositions.
- `.breadcrumbs`, `.post-header`, `.post-content`, `.post-toc`, and
  `.post-endnote` form long-form article compositions.
- `.page-hero`, `.content-page`, `.link-grid`, and `.empty-state` cover static
  and directory pages.
- `.error-panel` reuses the same tokens for 404 and 500 states without requiring
  Wagtail page context.

Templates should compose these primitives. New page-specific one-off colors,
type scales, shadows, or button styles should be promoted to a semantic token
or a shared primitive before use.

## Responsive behavior

- **Desktop (1100px and wider):** articles use a sticky 18rem outline rail;
  index mastheads and lead stories use split compositions.
- **Tablet (701px–1099px):** the article outline becomes the existing accessible
  drawer; mastheads and lead stories stack without changing reading order.
- **Mobile (700px and narrower):** navigation is compressed, RSS moves to the
  footer, metadata stacks, article padding tightens, and all cards become one
  column. Touch targets remain at least 44px where controls are present.

No meaningful content is hidden at a breakpoint.

## Accessibility and performance

- A skip link precedes the shared shell.
- Native landmarks, labeled navigation, semantic dates, breadcrumb state, and
  outline button relationships are present in templates.
- `:focus-visible` uses the high-contrast ember signal globally.
- Muted text is never used for primary article copy.
- Decorative field plots are CSS-only and `aria-hidden`; content images remain
  real Wagtail renditions.
- Index images below the lead story use lazy loading and async decoding.
- The system loads no web font, framework, or decorative image dependency.
- Motion is disabled under `prefers-reduced-motion`.

When visually reviewing a change, check the index, About page, 404, one
text-heavy article, and one diagram/image-heavy article at 390px and 1440px
widths. Also verify keyboard focus, the mobile outline drawer, horizontal table
and math overflow, and the RSS/sitemap routes.
