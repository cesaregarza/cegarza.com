# cegarza.com public design system

The public blog uses the **Console + series** direction: one flat page surface,
lowercase monospace chrome, Archivo headings, and structural hairlines. Content
is grouped by hierarchy rather than placed inside floating cards.

## Principles

1. **The page is the surface.** Header, hero, lists, article rail, and footer are
   bands in one grid. A one-pixel rule separates regions; nothing floats above
   the page.
2. **Hierarchy comes from type.** Archivo carries titles and headings. IBM Plex
   Sans carries reading copy. IBM Plex Mono is reserved for navigation,
   metadata, labels, code, and numeric status. IBM Plex Serif carries the body
   of an essay and nothing else.
3. **Chrome is lowercase, content is not.** Mono labels use
   `text-transform: lowercase`; author names, post titles, and series names opt
   out so source content keeps its intended casing.
4. **Accent means state.** Fuchsia marks the current page, newest content, and
   in-page navigation. Purple is reserved for series identity and progress.
5. **Nothing jumps on hover.** Hover changes color or a flat background only.
   Entry animations, lifts, zooms, shadows, and decorative washes are absent.

## Canonical tokens

Tokens live at the top of `src/static/css/site.css`.

| Group | Contract |
| --- | --- |
| Surfaces | `--color-bg`, `--color-surface`, `--color-surface-2`, `--color-surface-sunk`, `--color-surface-rail` |
| Structure | `--rule`, `--rule-soft` |
| Text | `--color-text-primary`, `--color-text-secondary`, `--color-text-muted`, `--color-text-disabled` |
| Active state | `--accent*` |
| Series | `--series*` |
| Callouts | `--cat-explainer`, `--cat-technical`, `--cat-extra`, `--cat-subquest`, each with a `-on` partner for a label set on that colour |
| Type | `--font-ui`, `--font-head`, `--font-mono`, `--font-serif`, `--measure-reading` |
| Chrome sizes | `--text-chrome` for mono navigation, metadata, and labels; `--text-micro` for the smallest status text |
| Essays | `--essay-column`, `--essay-text` |

The dark palette is the default. `prefers-color-scheme: light` switches the
document to the light palette, and a `data-theme="light|dark"` attribute on
`html` can override the OS choice. The light palette restates the series and
callout colours, because the dark values are too pale to read on a light
surface. All four font families are self-hosted in `src/static/fonts/` with
`font-display: swap`.

Every text, accent, series, and callout colour reads at 4.5:1 or better on
every surface of its palette, and so does each `-on` colour on its fill.
`--color-text-disabled` is the exception: it is for inactive controls and
separators only, never for words a reader is meant to read.

## Reusable primitives

- `.site-title`, `.site-nav`, `.reading-progress`, and `.site-footer` form the
  shared chrome. The header menu is `writing / essays / series / about` on
  every page; a link appears only when its destination exists. Feeds and the
  applets list stay in the footer and on the writing page.
- `.index-hero`, `.index-stats`, `.lead-post`, `.series-group`, `.post-grid`,
  and `.pagination` form the publication index.
- `.series-hero`, `.series-card`, `.series-progress`, and `.series-part` form
  series indexes and hubs.
- `.post-series-band`, `.post-header`, `.post-rail`, `.post-toc`,
  `.post-actions`, `.post-series-end`, and `.post-nav` form long-form posts.
  In a series the end card links the next part and `.post-nav` links back to
  the series, so the same destination is never offered twice.
- `.page--essay` is the essay variant of a post, applied to posts tagged
  `essays`. It drops the rail, contents drawer, and reading status for one
  centred `--essay-column` column, sets the body in the serif, and moves the
  byline under the title. Previous and next stay within the essays.
- `.takeaway`, `.collapsible-block`, `.glossary-tooltip`, `.code-block`,
  `.applet-embed`, tables, and blockquotes share the same two-pixel-or-less
  radius and rule system.
- `.content-page`, `.directory-grid`, and `.error-state` cover public pages
  outside the main publication flow. `.content-page` is a single column. Error
  pages render inside the same header and footer as every other page.

## Series content contract

`BlogSeries` is a Wagtail snippet. Editors set its stable slug, description,
ongoing/complete status, optional next-up note, and drag ordered
`BlogSeriesMembership` rows. A post can belong to more than one series, but a
database constraint allows at most one membership to be primary; that primary
series owns the article band and previous/next sequence.

The public series hub is `/series/`, details are `/series/<slug>/`, and each
detail has RSS and Atom feeds. Every index, count, rail, feed, and sitemap entry
is assembled from `BlogPage.objects.live().public()` under the Wagtail Site
selected for the request. Draft, restricted, cross-site, or otherwise
non-public posts therefore never create a public part or an empty detail route.

## Responsive contract

- **1100px and wider:** posts use a 236px sticky rail and a flexible article
  column; post and directory indexes use two columns.
- **700–1099px:** the rail becomes the existing right-hand drawer with a scrim;
  grid lists collapse to one column.
- **Below 700px:** gutters become 16px, titles become 27px, featured images use
  a 150px crop, series bands wrap, and interactive targets remain at least
  44px. The header stays on one row.
- **Below 360px:** the title and menu tighten once more so the header still
  fits on one row.

No meaningful content is hidden at a breakpoint. Three pieces of chrome give
way when there is no room for them, and each remains reachable another way:

- the reading status text below 900px (the progress bar stays);
- the header menu below 700px on a post that has a contents drawer, where the
  header holds the `contents` control instead (the drawer and the footer still
  link out);
- the paragraph anchor marks below 700px.

## Accessibility and performance

- A skip link precedes the sticky header.
- Every interactive control has a global `:focus-visible` outline.
- The mobile contents drawer retains its labeled control, scrim, Escape
  handling, and focusable links.
- Body copy remains at least 15px with a maximum 62-character measure. Essays
  use a larger serif on the `--essay-column` column instead.
- Tables, code, math, and applets contain their own horizontal overflow.
- Only the functional two-pixel reading-progress bar uses a gradient.
- `prefers-reduced-motion` removes transition duration.
- The index lead image is eager; subsequent content and Wagtail block images
  remain lazy.

Visual review covers the index, About, 404, a text-heavy post, an essay, and a
diagram/image/table/code-heavy post at 390px and 1440px, in both the dark and
the light palette. Header changes add 360px and 320px. Series work adds the
series hub, a first part, a current middle part, and an incomplete latest part
to the same matrix.
