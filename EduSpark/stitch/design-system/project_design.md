---
name: Nocturne Liquid Luxe
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#393939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1b1b1b'
  surface-container: '#1f1f1f'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353535'
  on-surface: '#e2e2e2'
  on-surface-variant: '#c4c7c8'
  inverse-surface: '#e2e2e2'
  inverse-on-surface: '#303030'
  outline: '#8e9192'
  outline-variant: '#444748'
  surface-tint: '#c6c6c7'
  primary: '#ffffff'
  on-primary: '#2f3131'
  primary-container: '#e2e2e2'
  on-primary-container: '#636565'
  inverse-primary: '#5d5f5f'
  secondary: '#c6c6cb'
  on-secondary: '#2f3034'
  secondary-container: '#45474b'
  on-secondary-container: '#b4b5ba'
  tertiary: '#ffffff'
  on-tertiary: '#2f3034'
  tertiary-container: '#e3e2e7'
  on-tertiary-container: '#636469'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e2e2e2'
  primary-fixed-dim: '#c6c6c7'
  on-primary-fixed: '#1a1c1c'
  on-primary-fixed-variant: '#454747'
  secondary-fixed: '#e2e2e7'
  secondary-fixed-dim: '#c6c6cb'
  on-secondary-fixed: '#1a1c1f'
  on-secondary-fixed-variant: '#45474b'
  tertiary-fixed: '#e3e2e7'
  tertiary-fixed-dim: '#c6c6cb'
  on-tertiary-fixed: '#1a1b1f'
  on-tertiary-fixed-variant: '#46464b'
  background: '#131313'
  on-background: '#e2e2e2'
  surface-variant: '#353535'
typography:
  display-hero:
    fontFamily: Instrument Serif
    fontSize: 80px
    fontWeight: '400'
    lineHeight: 84px
    letterSpacing: -0.03em
  display-hero-mobile:
    fontFamily: Instrument Serif
    fontSize: 44px
    fontWeight: '400'
    lineHeight: 48px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Instrument Serif
    fontSize: 56px
    fontWeight: '400'
    lineHeight: 60px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Instrument Serif
    fontSize: 34px
    fontWeight: '400'
    lineHeight: 38px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Instrument Serif
    fontSize: 36px
    fontWeight: '400'
    lineHeight: 42px
    letterSpacing: -0.01em
  headline-md-mobile:
    fontFamily: Instrument Serif
    fontSize: 26px
    fontWeight: '400'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-italic-accent:
    fontFamily: Instrument Serif
    fontSize: 36px
    fontWeight: '400'
    lineHeight: 42px
    letterSpacing: -0.01em
  body-lead:
    fontFamily: Geist
    fontSize: 18px
    fontWeight: '300'
    lineHeight: 28px
    letterSpacing: -0.01em
  body-base:
    fontFamily: Geist
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: 0em
  body-sm:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-caps:
    fontFamily: Geist
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.12em
  label-mono:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0.04em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-mobile: 1rem
  margin: 4rem
  margin-mobile: 1.25rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
  space-2xl: 4rem
  space-3xl: 6rem
---

## Brand & Style
This design system defines a high-end, editorial, cinematic digital space built on tension between pure void and luminous liquid glass. It targets discerning clientele, creators, and patrons of modern luxury, haute horlogerie, high architecture, and bespoke digital artifacts. 

The emotional response is quiet authority, intimacy, and architectural precision. The visual style merges **Atmospheric Minimalism** with **Liquid Glassmorphism**:
- Obsidian canvas (`#000000`) grounding the entire viewport to eliminate digital noise.
- Translucent, light-refracting glass panels that mimic cut optical crystal floating in complete darkness.
- Controlled monochrome white reflections, high-specular rim lighting, and whispering typography that prioritizes editorial pacing over aggressive visual density.

## Colors
The palette is rigorously monochrome, deriving hierarchy through opacity scales, refraction indices, and luminance rather than hue:

- **Base Void**: `#000000` serves as the absolute canvas. No tinted grays or dark blues are permitted as base backgrounds.
- **Pure Specular**: `#FFFFFF` reserved strictly for active elements, primary headlines, keyframe borders, and luminous gleams.
- **Glass Core Tiers**: 
  - `Surface Glass Ultra-Thin`: `rgba(255, 255, 255, 0.02)` for broad background section dividers and subtle card canvases.
  - `Surface Glass Standard`: `rgba(255, 255, 255, 0.05)` for floating interactive cards and media panels.
  - `Surface Glass Elevated`: `rgba(255, 255, 255, 0.09)` for modal overlays, floating dock navigations, and hover-state focus layers.
- **Liquid Rim Edges**:
  - `Border Idle`: Linear gradient transitioning from `rgba(255, 255, 255, 0.18)` at the top light-incidence source to `rgba(255, 255, 255, 0.02)` at the baseline shadow.
  - `Border Active / Specular Hit`: Dual layered stroke peaking at `rgba(255, 255, 255, 0.50)` for interactive feedback.
- **Muted Hierarchy**: Secondary text at `#D1D1D6`, sub-captions and metadata at `#8E8E93`, and passive micro-rules at `rgba(255, 255, 255, 0.08)`.

## Typography
Typographic discipline pairs the bespoke, haute-couture cadence of `Instrument Serif` (both Regular and Italic) with the hyper-refined, neutral precision of `Geist`.

- **Display & Headings**: `Instrument Serif` carries the editorial weight. Use italicized variants selectively—ideal for pivotal words within a title (e.g., "The *Atmospheric* Continuum") to evoke couture provenance.
- **Body & Structural Text**: `Geist` provides invisible, high-legibility support. The light weight (`300`) is leveraged across narrative summaries to avoid competing with glass refraction lines.
- **Labels & Micro-Metrics**: `label-caps` enforces high letter-spacing (0.12em) and uppercase transformation for badges, video timestamps, categories, and luxury specification data.

## Layout & Spacing
The layout follows an airy, structural 12-column grid system designed for expansive widescreen resolutions while scaling fluidly down to single-column handheld screens.

- **Desktop (1200px and up)**: 12-column grid with a maximum bounded content container of `1440px`. Exterior margins expand to `margin` (4rem) or float centered. Gutters remain fixed at `1.5rem` to keep video assets tightly composed.
- **Tablet (768px – 1199px)**: 8-column grid with `margin: 2.5rem` and `gutter: 1.25rem`. Two-column layouts compress cleanly into stacked 4-column blocks.
- **Mobile (< 768px)**: 4-column grid with `margin-mobile: 1.25rem` and `gutter-mobile: 1rem`. Hero headlines swap automatically to `-mobile` typography scale tokens.
- **Rhythm**: Generous vertical section spacing (`space-3xl`) isolates each visual chapter against the pitch-black void, avoiding visual clutter and amplifying focus on single interactive showcases.

## Elevation & Depth
Depth is produced through light physics—transmission, optical diffusion, and acute directional rim lights—rather than traditional drop shadows.

1. **Backdrop Filtration**:
   All elevated surfaces enforce backdrop filters with a blur of `24px` to `40px` and saturate multiplier of `140%`.
2. **The "Liquid Specular" Border**:
   Surfaces do not use static borders. They utilize a 1px pseudo-inner stroke or gradient border:
   - `top`: `rgba(255, 255, 255, 0.25)` catching phantom directional light.
   - `sides`: `rgba(255, 255, 255, 0.08)`.
   - `bottom`: `rgba(255, 255, 255, 0.02)` sinking back into the `#000000` canvas.
3. **Ambient Halo (Glow Tier)**:
   Video cards and floating interaction bars cast an ethereal, extra-diffused luminance:
   `box-shadow: 0 20px 80px -20px rgba(255, 255, 255, 0.06), 0 0 1px 1px rgba(255, 255, 255, 0.12) inset`.
4. **Z-Index Layering**:
   - Level 0: Pure pitch background canvas (`#000000`).
   - Level 1: Inactive video/editorial containers (backdrop blur `16px`).
   - Level 2: Active or hovered liquid glass surfaces (backdrop blur `32px`, top specular rim illumination).
   - Level 3: Navigation floating capsule and bespoke media modals (backdrop blur `48px`, full rim light).

## Shapes
Shapes evoke precision-machined crystal and smooth liquid lens profiles. The system anchors to `roundedness: 2` (base `0.5rem` / 8px).

- **Standard Interactive Elements**: Buttons, text inputs, and dropdown selectors sit at `0.5rem` (8px).
- **Cards & Video Viewports (`rounded-lg`)**: `1rem` (16px) corner radius to ensure media corners feel organic yet architectural.
- **Floating Controls & Badges (`rounded-xl` / Pill)**: Audio pills, timeline indicators, and floating navigation bars adopt an ultra-soft curve (`1.5rem` to full pill `9999px`) to visually soften technical controls.

## Components

### Ultra-Refined Video Cards
- **Base Canvas**: 16:9 or 4:5 aspect ratio wrapper with `1rem` radius. Background sits at `rgba(255, 255, 255, 0.02)` before load.
- **Liquid Border**: Dual gradient outline with top-edge white luminosity (`rgba(255, 255, 255, 0.22)`) tapering into the black void.
- **Video Surface**: Masked with a fine micro-vignette (`linear-gradient(180deg, transparent 60%, rgba(0,0,0,0.85) 100%)`).
- **Interactive State**: On hover, the inner glass border lightens to `rgba(255, 255, 255, 0.45)`, and an ambient back-glow (`0 0 50px rgba(255, 255, 255, 0.08)`) emerges smoothly over 600ms.
- **Overlay HUD**: Timestamps, chapter titles, and audio indicators utilize `label-mono` and `label-caps` in frosted pill badges resting in the bottom-left and bottom-right corners.

### Buttons
- **Primary Glass Action**:
  - Background: `rgba(255, 255, 255, 0.08)`.
  - Border: 1px liquid gradient border with upper white specular highlight.
  - Backdrop blur: `20px`.
  - Text: `Geist` Medium, `#FFFFFF`, tracking +0.02em.
  - Hover: Background transitions to `rgba(255, 255, 255, 0.16)`; subtle inset shadow bloom (`inset 0 1px 1px rgba(255, 255, 255, 0.4)`).
- **Secondary Ghost Action**:
  - Background: Transparent.
  - Text: `Geist` Regular, `#D1D1D6`.
  - Underline: Micro-hairline (0.5px) in `rgba(255, 255, 255, 0.3)` that expands on hover to `#FFFFFF`.

### Chips & Metadata Tags
- Built with a full pill radius.
- Height: 26px with vertical padding `space-xs` and horizontal padding `space-sm`.
- Glass surface: `rgba(255, 255, 255, 0.04)` with `backdrop-filter: blur(12px)`.
- Typography: `label-caps` in `#D1D1D6`.

### Inputs & Text Fields
- Background: `rgba(255, 255, 255, 0.03)`.
- Border: 1px stroke at `rgba(255, 255, 255, 0.1)`.
- Text: `#FFFFFF`, placeholder in `#8E8E93`.
- Focus State: Border color moves to `#FFFFFF` with a localized directional gleam; glow diffuse `0 0 20px rgba(255, 255, 255, 0.1)`. No default browser rings.

### Checkboxes & Radios
- Size: 18px by 18px.
- Unchecked: Frosted void (`rgba(255, 255, 255, 0.05)`) with 1px rim border.
- Checked: Pure `#FFFFFF` fill with an optical pitch-black (`#000000`) inner checkmark or pip.

### Floating Dock Navigation (Special Component)
- Positioned fixed along the viewport bottom.
- Pill-shaped frame with `backdrop-filter: blur(32px)`, background `rgba(255, 255, 255, 0.05)`, and continuous liquid edge reflection.
- Houses navigation anchors set in `label-caps` separated by hairline dividers (`rgba(255, 255, 255, 0.12)`).