## Brand & Style
This design system defines a high-end, editorial, cinematic digital space built on tension between pure void and luminous liquid glass. It targets discerning clientele, creators, and patrons of modern luxury, haute horlogerie, high architecture, and bespoke digital artifacts. 

The emotional response is quiet authority, intimacy, and architectural precision. The visual style merges **Atmospheric Minimalism** with **Liquid Glassmorphism**:
- Obsidian canvas (`#000000`) grounding the entire viewport to eliminate digital noise.
- Translucent, light-refracting glass panels that mimic cut optical crystal floating in complete darkness.
- Controlled monochrome white reflections, high-specular rim lighting, and whispering typography that prioritizes editorial pacing over aggressive visual density.

## Layout & Spacing
The layout follows an airy, structural 12-column grid system designed for expansive widescreen resolutions while scaling fluidly down to single-column handheld screens.

- **Desktop (1200px and up)**: 12-column grid with a maximum bounded content container of `1440px`. Exterior margins expand to `margin` (4rem) or float centered. Gutters remain fixed at `1.5rem` to keep video assets tightly composed.
- **Tablet (768px â€“ 1199px)**: 8-column grid with `margin: 2.5rem` and `gutter: 1.25rem`. Two-column layouts compress cleanly into stacked 4-column blocks.
- **Mobile (< 768px)**: 4-column grid with `margin-mobile: 1.25rem` and `gutter-mobile: 1rem`. Hero headlines swap automatically to `-mobile` typography scale tokens.
- **Rhythm**: Generous vertical section spacing (`space-3xl`) isolates each visual chapter against the pitch-black void, avoiding visual clutter and amplifying focus on single interactive showcases.

## Elevation & Depth
Depth is produced through light physicsâ€”transmission, optical diffusion, and acute directional rim lightsâ€”rather than traditional drop shadows.

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