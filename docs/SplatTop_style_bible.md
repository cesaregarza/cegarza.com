# SplatTop Style Bible

A comprehensive design system guide for the SplatTop frontends, with emphasis on the darker, purple aesthetic from `comp.splat.top`.

---

## Table of Contents

1. [Color System](#color-system)
2. [Typography](#typography)
3. [Spacing & Layout](#spacing--layout)
4. [Components](#components)
5. [Animations & Effects](#animations--effects)
6. [Accessibility](#accessibility)

---

## Color System

### Brand Colors (Primary Palette)

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| **Purple** (Primary) | `#ab5ab7` | `rgb(171, 90, 183)` | Brand color, scrollbars, highlights, animated dots |
| **Purple Dark** | `#7b28a4` | `rgb(123, 40, 164)` | Darker accents, depth |
| **Purple Light** | `#c183e1` | `rgb(193, 131, 225)` | Highlights, branding text accents |

### Competition Accent Colors (comp.splat.top)

| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| **Fuchsia/Magenta** | `#c026d3` | `rgb(192, 38, 211)` | Primary accent, buttons, sliders |
| **Fuchsia Light** | `#d946ef` | `rgb(217, 70, 239)` | Gradients, glows, top-tier badges |
| **Fuchsia Lighter** | `#e879f9` | `rgb(232, 121, 249)` | Hover states |
| **Pink** | `#ec4899` | `rgb(236, 72, 153)` | Secondary gradients |
| **Rose** | `#f472b6` | `rgb(244, 114, 182)` | Glow effects |

### Background Colors

| Name | Hex | Opacity | Usage |
|------|-----|---------|-------|
| **Surface Dark** | `#0f172a` | 100% | Base background (slate-900) |
| **Surface Elevated** | `rgba(15, 23, 42, 0.55)` | 55% | Cards, panels |
| **Surface Subtle** | `rgba(255, 255, 255, 0.022)` | 2.2% | Elevated surfaces |
| **Surface Hint** | `rgba(13, 17, 23, 0.74)` | 74% | Tooltips, hints |
| **App Header** | `#282c34` | 100% | Legacy header background |
| **Gray 900** | `#1F2937` | 100% | Navbar, footer, scrollbar track |

### Text Colors

| Name | Hex | Usage |
|------|-----|-------|
| **Primary** | `#ffffff` | Main text on dark backgrounds |
| **Secondary** | `#c9d1d9` | Secondary text, hints |
| **Muted** | `#8b949e` | Subtle labels |
| **Purple Text** | `#e6e6f0` | Default badge/chip text |

### Tier System Colors

#### XX Tier (Top - Strong Visual Presence)

| Tier | Background | Text | Border | Glow |
|------|------------|------|--------|------|
| **XX Star** | `linear-gradient(135deg, rgba(217,70,239,0.22), rgba(244,63,94,0.22))` | `#fde2f2` | `rgba(217,70,239,0.45)` | Pink/Purple intense |
| **XX Plus** | `linear-gradient(135deg, rgba(217,70,239,0.18), rgba(236,72,153,0.18))` | `#f6e7fb` | `rgba(217,70,239,0.35)` | Purple medium |
| **XX** | `linear-gradient(135deg, rgba(217,70,239,0.12), rgba(236,72,153,0.12))` | `#f3e8ff` | `rgba(217,70,239,0.28)` | Purple subtle |

#### XS Tier (High - Subtle Glow)

| Tier | Background | Text | Border |
|------|------------|------|--------|
| **XS Plus** | `linear-gradient(135deg, rgba(139,92,246,0.22), rgba(99,102,241,0.22))` | `#ede9fe` | `rgba(139,92,246,0.28)` |
| **XS** | `linear-gradient(135deg, rgba(139,92,246,0.18), rgba(99,102,241,0.18))` | `#e9d5ff` | `rgba(139,92,246,0.24)` |
| **XS Minus** | `linear-gradient(135deg, rgba(139,92,246,0.14), rgba(99,102,241,0.14))` | `#e9d5ff` | `rgba(139,92,246,0.2)` |

#### XA Tier (Mid - Cyan/Sky)

| Tier | Background | Text | Border |
|------|------------|------|--------|
| **XA Plus** | `rgba(56,189,248,0.18)` | `#cffafe` | `rgba(56,189,248,0.25)` |
| **XA** | `rgba(56,189,248,0.14)` | `#e0f2fe` | `rgba(56,189,248,0.18)` |
| **XA Minus** | `rgba(56,189,248,0.10)` | `#e0f2fe` | `rgba(56,189,248,0.14)` |

#### XB Tier (Lower - Slate)

| Tier | Background | Text | Border |
|------|------------|------|--------|
| **XB Plus** | `rgba(100,116,139,0.20)` | `#e2e8f0` | `rgba(148,163,184,0.20)` |
| **XB** | `rgba(100,116,139,0.16)` | `#e2e8f0` | `rgba(148,163,184,0.18)` |
| **XB Minus** | `rgba(100,116,139,0.12)` | `#e2e8f0` | `rgba(148,163,184,0.14)` |

#### Default Tier

| Background | Text | Border |
|------------|------|--------|
| `rgba(51,65,85,0.4)` | `#e5e7eb` | `rgba(255,255,255,0.08)` |

### Special Colors

| Name | Hex | Usage |
|------|-----|-------|
| **XX Star Score** | `#fde68a` | Special score display (amber/gold) |
| **Zap/Spark** | `#a78bfa` | Electric crackle effects (violet) |
| **Gold Glow** | `rgba(255, 215, 0, 0.8-1.0)` | Gold badge animations |
| **Badge Count** | `#ff0000` | Notification badges |

### Seasonal/Chart Color Palettes

#### Classic
- `#ab5ab7` (solid purple)

#### Seasonal Gradient
```css
linear-gradient(to right top, #00ff55 23%, #ffe900 26% 49%, #cc6600 52% 75%, #0087cc 78%)
```

#### Accessible (Colorblind-Friendly)
```css
linear-gradient(to left top, #117733 23%, #ddcc77 26% 49%, #aa4499 52% 75%, #332288 78%)
```

### Blog Graphics Palette

Used for LOOPR blog charts and applets.

- Background: `#0f172a`
- Panel: `#111827`
- Text: `#ffffff`
- Muted text: `#c9d1d9`
- Accents: `#ab5ab7` (purple), `#c183e1` (purple light), `#c026d3` (fuchsia),
  `#d946ef` (fuchsia light), `#ec4899` (pink), `#f472b6` (rose), `#38bdf8`
  (cyan)
- Grid: `rgba(255, 255, 255, 0.08)`
- Borders: `rgba(255, 255, 255, 0.12)`

---

## Typography

### Font Families

| Family | Usage | Fallbacks |
|--------|-------|-----------|
| **System Font Stack** | Body text | `-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif` |
| **FiraMono** | Data/numbers | `monospace` |
| **FiraMono-Bold** | Bold data | `monospace` |
| **FiraMono-Medium** | Medium weight data | `monospace` |
| **Code Font** | Code blocks | `source-code-pro, Menlo, Monaco, Consolas, 'Courier New', monospace` |

### Font Files

Located in `src/react_app/src/assets/fonts/`:
- `FiraMono-Regular.woff2`
- `FiraMono-Bold.woff2`
- `FiraMono-Medium.woff2`

### CSS Custom Properties

```css
:root {
  --font-data: "FiraMono", monospace;
}

.font-data {
  font-family: var(--font-data, "FiraMono", monospace);
  font-variant-numeric: tabular-nums;
}
```

### Font Sizes

| Element | Size | Weight |
|---------|------|--------|
| Logo | `text-xl` / `text-2xl` | Bold |
| Badge | `12px` | 600 |
| Chip | `0.85rem` | 600 |
| Hint text | `0.78rem` | Normal |
| Small hint | `0.7rem` | Normal |
| Skip button | `0.75rem` | Normal (uppercase) |

### Text Rendering

```css
-webkit-font-smoothing: antialiased;
-moz-osx-font-smoothing: grayscale;
```

---

## Spacing & Layout

### Border Radius Scale

| Name | Value | Usage |
|------|-------|-------|
| **Small** | `5px` | Scrollbar thumb |
| **Medium** | `8px` | Badges, chips |
| **Large** | `12px` | Hints, small buttons |
| **XL** | `16px` | Cards, panels, canvas shells |
| **Full** | `9999px` | Pills, circular buttons |

### Box Shadows

#### Panels & Cards
```css
/* Standard panel */
box-shadow: 0 10px 26px rgba(1, 4, 9, 0.45);

/* Canvas shell (elevated) */
box-shadow:
  inset 0 1px 0 rgba(255, 255, 255, 0.04),
  0 18px 42px rgba(1, 4, 9, 0.65);

/* Accent panel */
box-shadow:
  0 14px 36px rgba(1, 4, 9, 0.65),
  inset 0 0 0 1px rgba(217, 70, 239, 0.08);
```

#### Buttons
```css
/* Primary button */
box-shadow: 0 12px 30px rgba(217, 70, 239, 0.25);

/* Primary button hover */
box-shadow: 0 14px 32px rgba(217, 70, 239, 0.35);

/* Skip button */
box-shadow: 0 10px 25px rgba(217, 70, 239, 0.32);
```

#### Badge Glows
```css
/* XX Star tier */
box-shadow: 0 0 0 2px rgba(217,70,239,0.24) inset,
            0 0 12px rgba(244,114,182,0.45),
            0 0 22px rgba(244,114,182,0.25);

/* XS tier */
box-shadow: 0 0 10px rgba(139,92,246,0.38),
            0 0 18px rgba(99,102,241,0.25);
filter: drop-shadow(0 0 6px rgba(139,92,246,0.25));
```

### Border Styles

```css
/* Standard subtle border */
border: 1px solid rgba(255, 255, 255, 0.08);

/* Panel border */
border: 1px solid rgba(255, 255, 255, 0.03);

/* Button borders */
border: 1px solid transparent;
border-color: rgba(217, 70, 239, 0.55); /* primary */
border-color: rgba(255, 255, 255, 0.1); /* secondary */
```

### Responsive Heights

```css
/* Canvas shell fluid height */
min-height: 420px;
height: clamp(420px, 65vh, 780px);
```

---

## Components

### Buttons

#### Primary Button
```css
.button-primary {
  background: linear-gradient(135deg, rgba(217, 70, 239, 0.95), rgba(192, 38, 211, 0.9));
  color: #fff;
  border-color: rgba(217, 70, 239, 0.55);
  border-radius: 9999px;
  font-weight: 600;
  font-size: 0.9rem;
  padding: 0.55rem 0.75rem;
  box-shadow: 0 12px 30px rgba(217, 70, 239, 0.25);
  transition: transform 120ms ease, box-shadow 120ms ease, background 120ms ease;
}

.button-primary:hover {
  background: linear-gradient(135deg, rgba(232, 121, 249, 0.95), rgba(217, 70, 239, 0.92));
  box-shadow: 0 14px 32px rgba(217, 70, 239, 0.35);
}

.button-primary:active {
  transform: scale(0.98);
}

.button-primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}
```

#### Secondary Button
```css
.button-secondary {
  background: rgba(255, 255, 255, 0.03);
  color: #c9d1d9;
  border-color: rgba(255, 255, 255, 0.1);
}

.button-secondary:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.12);
  color: #fff;
}
```

#### Ghost Button
```css
.button-ghost {
  background: transparent;
  color: #c9d1d9;
  border-color: rgba(255, 255, 255, 0.1);
}

.button-ghost:hover {
  background: rgba(255, 255, 255, 0.04);
  color: #fff;
  border-color: rgba(255, 255, 255, 0.12);
}
```

### Badges & Chips

```css
.grade-badge,
.grade-chip {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #e6e6f0;
  background: #0f172a;
  min-width: 3.25rem;
  font-family: var(--font-data, "FiraMono", monospace);
}

.grade-badge {
  padding: 2px 8px;
  font-weight: 600;
  font-size: 12px;
  line-height: 1.25;
}

.grade-chip {
  padding: 6px 12px;
  font-weight: 600;
  font-size: 0.85rem;
  min-width: 3.5rem;
  transition: transform 150ms ease;
}

.grade-chip:hover {
  transform: scale(1.05);
}

.grade-chip.is-active {
  transform: scale(1.02);
}
```

### Panels & Cards

```css
.panel {
  background: rgba(255, 255, 255, 0.022);
  border: 1px solid rgba(255, 255, 255, 0.03);
  border-radius: 16px;
  box-shadow: 0 10px 26px rgba(1, 4, 9, 0.45);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.panel-accent {
  box-shadow:
    0 14px 36px rgba(1, 4, 9, 0.65),
    inset 0 0 0 1px rgba(217, 70, 239, 0.08);
}
```

### Sliders

```css
.slider {
  width: 100%;
  -webkit-appearance: none;
  appearance: none;
  background: transparent;
  cursor: pointer;
}

/* Track */
.slider::-webkit-slider-runnable-track {
  height: 6px;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(217, 70, 239, 0.75), rgba(192, 38, 211, 0.65));
}

/* Thumb */
.slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  margin-top: -4px;
  background: #f5d0fe;
  border: 2px solid #d946ef;
  box-shadow: 0 0 12px rgba(217, 70, 239, 0.55);
}
```

### Scrollbar

```css
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

::-webkit-scrollbar-track {
  background: #1F2937;
}

::-webkit-scrollbar-thumb {
  background: #ab5ab7;
  border-radius: 5px;
  border: 1px solid #1F2937;
}
```

### Navigation Links

```css
/* Link default */
.nav-link {
  color: white;
  transition: duration-300;
}

/* Link hover */
.nav-link:hover {
  color: #ab5ab7; /* text-purple */
  /* OR */
  background-color: #ab5ab7; /* bg-purple */
}
```

---

## Animations & Effects

### CSS Custom Properties (Tunables)

```css
:root {
  --zap-color: #a78bfa;
  --ring: 6px;
  --zap-cycle-xxstar: 2200ms;
  --zap-cycle-xxplus: 2400ms;
  --zap-cycle-xx: 2600ms;
  --xs-glow-scale-min: 0.9;
  --xs-glow-scale-max: 1.05;
  --xs-glow-opacity-min: 0.25;
  --xs-glow-opacity-max: 0.42;
  --xs-glow-blur: 14px;
}
```

### Keyframe Animations

#### White Glow (Silver Badges)
```css
@keyframes glow {
  0%, 100% {
    filter: drop-shadow(0 0 3px rgba(255, 255, 255, 0.7)) brightness(1);
  }
  50% {
    filter: drop-shadow(0 0 5px rgba(255, 255, 255, 0.9)) brightness(1.1);
  }
}
/* Duration: 5s ease-in-out infinite */
```

#### Gold Glow (Gold Badges)
```css
@keyframes glow-gold {
  0%, 100% {
    filter: drop-shadow(0 0 4px rgba(255, 215, 0, 0.8)) brightness(1);
  }
  25%, 75% {
    filter: drop-shadow(0 0 6px rgba(255, 215, 0, 0.9)) brightness(1.1);
  }
  50% {
    filter: drop-shadow(0 0 10px rgba(255, 215, 0, 1)) brightness(1.2);
  }
}
/* Duration: 5s ease-in-out infinite */
```

#### Gold Ultra Glow (High-Value Gold Badges)
```css
@keyframes glow-gold-ultra-value {
  0%, 100% {
    filter: drop-shadow(0 0 6px rgba(255, 215, 0, 0.9)) brightness(1.1) contrast(100%);
  }
  25%, 75% {
    filter: drop-shadow(0 0 8px rgba(255, 215, 0, 1)) brightness(1.2) contrast(110%);
  }
  50% {
    filter: drop-shadow(0 0 12px rgba(255, 215, 0, 1.1)) brightness(1.3) contrast(120%);
  }
}
```

#### Rainbow Glow (Special Badges)
```css
@keyframes glow-rainbow {
  0%, 100% {
    filter: drop-shadow(0 0 12px hsl(0, 100%, 80%)) brightness(1.1);
  }
  16.666%, 83.333% {
    filter: drop-shadow(0 0 12px hsl(60, 100%, 80%)) brightness(1.1);
  }
  33.333%, 66.666% {
    filter: drop-shadow(0 0 13px hsl(120, 100%, 80%)) brightness(1.2);
  }
  50% {
    filter: drop-shadow(0 0 13px hsl(180, 100%, 80%)) brightness(1.2);
  }
}
```

#### XX Tier Pulse
```css
@keyframes xxPulse {
  0%, 100% {
    transform: scale(0.97);
    opacity: 0.65;
    filter: blur(1.3px);
  }
  45% {
    transform: scale(1.03);
    opacity: 0.9;
    filter: blur(1.9px);
  }
  70% {
    transform: scale(1.01);
    opacity: 0.78;
    filter: blur(1.5px);
  }
}
/* Duration: 5200ms ease-in-out infinite */
```

#### XS Tier Glow Pulse
```css
@keyframes xsGlowPulse {
  0%, 100% {
    transform: scale(var(--xs-glow-scale-min, 0.9));
    opacity: var(--xs-glow-opacity-min, 0.25);
  }
  50% {
    transform: scale(var(--xs-glow-scale-max, 1.05));
    opacity: var(--xs-glow-opacity-max, 0.42);
  }
}
/* Duration: 4.8s ease-in-out infinite */
```

#### XX Star Score Pulse
```css
@keyframes xxScorePulse {
  0%, 100% {
    opacity: 0.5;
    transform: scale(0.97);
    filter: blur(1.1px);
  }
  45% {
    opacity: 0.75;
    transform: scale(1.02);
    filter: blur(1.5px);
  }
  70% {
    opacity: 0.6;
    transform: scale(1.0);
    filter: blur(1.2px);
  }
}
/* Duration: 4200ms ease-in-out infinite */
```

#### Expand Fade (Animated Dots)
```css
@keyframes expand-fade {
  0% {
    opacity: 0.3;
    transform: scale(1);
  }
  100% {
    opacity: 0;
    transform: scale(3);
  }
}
/* Duration: 2s ease-out infinite */
```

### Electric Crackle Effect

The crackle effect is a JavaScript-driven SVG animation that creates electric spark paths around elements.

**Usage:**
```jsx
import useCrackleEffect from './hooks/useCrackleEffect';

// In component
const rootRef = useRef(null);
useCrackleEffect(rootRef, [dependencies]);

// In JSX - add .crackle class to elements
<div ref={rootRef}>
  <span className="crackle" data-color="#a78bfa" data-rate="3">
    Content
  </span>
</div>
```

**CSS for Sparks:**
```css
.crackle-layer {
  position: absolute;
  inset: calc(var(--ring-pad, 10px) * -1);
  pointer-events: none;
  overflow: visible;
}

.spark {
  fill: none;
  stroke: var(--zap-color, #a78bfa);
  opacity: 0;
  stroke-linecap: round;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
  transition: opacity 90ms linear;
  filter:
    drop-shadow(0 0 2px var(--zap-color, #a78bfa))
    drop-shadow(0 0 7px var(--zap-color, #a78bfa));
}

.spark.show {
  opacity: 1;
}
```

### Badge Shine Effect

```css
.badge-shine {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(
    45deg,
    rgba(255, 255, 255, 0) 40%,
    rgba(255, 255, 255, 0.8) 50%,
    rgba(255, 255, 255, 0) 60%
  );
  opacity: 0;
  transition: opacity 0.3s ease-in-out;
  pointer-events: none;
}

.badge-container:hover .badge-shine {
  opacity: 1;
}
```

### Transition Defaults

```css
/* Standard transition */
transition: duration-300; /* Tailwind: 300ms */

/* Button transitions */
transition: transform 120ms ease, box-shadow 120ms ease, background 120ms ease;

/* Chip hover */
transition: transform 150ms ease;

/* Badge shine */
transition: opacity 0.3s ease-in-out;

/* Spark opacity */
transition: opacity 90ms linear;
```

---

## Accessibility

### Reduced Motion Support

All animations respect `prefers-reduced-motion`:

```css
@media (prefers-reduced-motion: reduce) {
  /* Disable all tier animations */
  .grade-badge.grade-tier-xxstar::before,
  .grade-chip.grade-tier-xxstar::before,
  /* ... */
  {
    animation: none;
    opacity: 0.9;
  }

  /* Static crackle fallback */
  .crackle-layer .spark {
    display: none;
  }
  .crackle-layer::after {
    content: "";
    position: absolute;
    inset: 0;
    border: 1px solid var(--zap-color, #a78bfa);
    border-radius: 999px;
    opacity: 0.5;
  }

  /* Disable button/slider transitions */
  .comp-viz__button,
  .comp-viz__slider::-webkit-slider-thumb,
  .comp-viz__slider::-moz-range-thumb {
    transition: none;
  }
}
```

### Color Contrast

- Primary text on dark background: White (`#ffffff`) on Gray 900 (`#1F2937`) - AAA compliant
- Secondary text: `#c9d1d9` on dark - AA compliant
- Badge text colors are carefully chosen per tier for readability

### Colorblind-Friendly Palette

For charts/visualizations, use the accessible gradient:
```css
background: linear-gradient(
  to left top,
  #117733 23%,  /* Green */
  #ddcc77 26% 49%,  /* Yellow */
  #aa4499 52% 75%,  /* Purple/Pink */
  #332288 78%   /* Deep Blue */
);
```

---

## Quick Reference

### Tailwind Classes Used

```
/* Backgrounds */
bg-gray-900, bg-purple, bg-purpledark, bg-purplelight

/* Text */
text-white, text-purple, text-purplelight

/* Effects */
hover:text-purple, hover:bg-purple

/* Layout */
sticky, top-0, z-50

/* Transitions */
transition, duration-300
```

### CSS Variables Summary

```css
:root {
  /* Colors */
  --color-purple: #ab5ab7;
  --color-purpledark: #7b28a4;
  --color-purplelight: #c183e1;

  /* Typography */
  --font-data: "FiraMono", monospace;

  /* Effects */
  --zap-color: #a78bfa;
  --ring: 6px;
  --ring-pad: 10px;

  /* Animation timing */
  --zap-cycle-xxstar: 2200ms;
  --zap-cycle-xxplus: 2400ms;
  --zap-cycle-xx: 2600ms;

  /* XS Glow tunables */
  --xs-glow-scale-min: 0.9;
  --xs-glow-scale-max: 1.05;
  --xs-glow-opacity-min: 0.25;
  --xs-glow-opacity-max: 0.42;
  --xs-glow-blur: 14px;
}
```

### Competition Viz Variables

```css
.comp-viz {
  --comp-viz-accent: #c026d3;
  --comp-viz-accent-soft: rgba(192, 38, 211, 0.18);
  --comp-viz-surface: rgba(255, 255, 255, 0.022);
}
```

---

## Blog-Specific Components

The SplatTop Blog is intentionally flatter than the product UI. The document is
the surface: `1px` structural rules replace elevated panels, and no blog
component uses blur, a drop shadow, a background wash, or more than a `2px`
radius. The only gradients are the functional `2px` reading-progress variants.

### Blog Typography

| Role | Family | Desktop size | Weight | Line height |
|------|--------|--------------|--------|-------------|
| Index title | Archivo | `44px` | 700 | 1.02 |
| Post title | Archivo | `46px` | 700 | 1.02 |
| Article h2 / h3 | Archivo | `26px` / `19px` | 700 / 600 | 1.2 / 1.3 |
| Body | IBM Plex Sans | `16px` | 400 | 1.8 |
| Metadata and navigation | IBM Plex Mono | `9.5–12.5px` | 400–600 | 1.4 |
| Code | IBM Plex Mono | `13px` | 400 | 1.7 |

Archivo, IBM Plex Sans, and IBM Plex Mono are self-hosted in
`src/static/fonts/`. Mono interface labels are lowercased with CSS; author
names, post titles, series names, and product names retain source casing.

### Index grid

The index hero, statistics, lead post, series groups, standalone grid, applet
directory, and pagination are full-width bands. `.post-cell` has no fill,
radius, border shell, shadow, or hover motion. Column and row rules provide all
separation.

Fuchsia identifies active/newest state. Purple identifies series. A series
progress control is always `116px` wide so segment count changes without
changing the component's visual weight.

### Collapsible Blocks

Collapsibles have a one-pixel category rule and a two-pixel radius. The summary
uses a flat category wash; its category badge is solid, and the toggle is a
monospace `+` / `−`. Open state adds only a bottom rule.

| Category | Model value | Accent | Wash | Rule |
|----------|-------------|--------|------|------|
| Explainer | `"explainer"` | `#7dd3fc` | sky 8% | sky 24% |
| Technical | `"technical"` | `#c183e1` | purple 10% | purple 30% |
| Extra | `"extra"` | `#f472b6` | pink 10% | pink 28% |
| Side Quest | `"subquest"` | `#fcd34d` | gold 9% | gold 28% |

### Key Takeaway Callouts

Takeaways reuse the category washes and rules above. There is no icon dot,
gradient, glow, or shadow. `.takeaway--series` uses the separate series palette
for recap content.

### Glossary Tooltips

Terms use a dashed fuchsia underline. The `300px` tooltip uses the standard
surface, a one-pixel accent rule, a two-pixel radius, and no blur or shadow.

### Table of Contents Sidebar

The desktop article rail is a `236px` structural column with series context,
contents, and actions. Active series rows use a purple two-pixel leading rule;
active headings use a fuchsia rule. Below `1100px`, the same rail becomes a
right-hand drawer over a dark scrim. The reading-progress bar sits flush with
the sticky header rather than inside a rail card.

---

## File Locations

### SplatTop Main App (comp.splat.top)

| File | Purpose |
|------|---------|
| `src/react_app/tailwind.config.js` | Tailwind theme configuration |
| `src/react_app/src/index.css` | Global styles, theme tokens, animations |
| `src/react_app/src/components/competition/StableLeaderboardView.css` | Tier badge/chip styles |
| `src/react_app/src/components/competition/CompetitionViz.css` | Competition visualization styles |
| `src/react_app/src/components/player_components/xchart.css` | Chart color palettes |
| `src/react_app/src/hooks/useCrackleEffect.js` | Electric spark animation hook |
| `src/react_app/src/assets/fonts/` | FiraMono font files |

### SplatTop Blog (blog.splat.top)

| File | Purpose |
|------|---------|
| `src/static/css/site.css` | All blog styles, CSS custom properties |
| `src/templates/base.html` | Base template with header, footer, KaTeX |
| `src/blog/templates/blog/blog_page.html` | Blog post template with TOC sidebar |
| `src/blog/templates/blog/blog_index_page.html` | Blog listing with post card grid |
| `src/blog/models.py` | StreamField block definitions |
| `src/blog/post_processing.py` | HTML post-processing (TOC, glossary, images) |
| `docs/SplatTop_style_bible.md` | This file |
