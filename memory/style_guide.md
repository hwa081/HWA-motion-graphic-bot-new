# Style guide (from 2 reference videos, updated 2026-11-09)

# MOTION GRAPHICS STYLE GUIDE: SAAS DASHBOARD SERIES

## 1. COMMON PATTERNS (THE CORE)
*   **Perspective:** Both styles utilize heavy **3D tilt** (approx. 20–30°) to create tangible depth. Avoid flat 2D layouts; everything must exist in z-space.
*   **Motion Physics:** Use **smooth exponential easing** for floating cards and **snappy direct cuts** for focal shifts. Motion should feel "heavy" yet fluid (like glass or polished plastic).
*   **Hierarchy:** Headlines occupy the **upper third**; UI clusters float below. Never crowd the center with text unless it's a hero statement.
*   **Layer Types:** Rely heavily on `card`, `chip`, `device`, and `blob` layers to simulate interface elements.

## 2. DESIGN RECIPES (THE LOOKS)

### Look A: "Neon Night Sports"
*Use this for high-energy, consumer-facing sports tech promos.*
*   **Palette:** `#000000` base + `#FF5517`/`#8C8C8E` accents. High contrast.
*   **Background:** `dark_aurora` with warm orange radial glows behind focal UI.
*   **Typography:** Bold, title-case headlines; crisp sans-serif body. No serifs.
*   **Motion Keywords:** `fly_through`, `parallax`, `depth_of_field`. Heavy camera movement in z-space.
*   **Transitions:** `star_scale_wipe` (for reveals), `glitch` (for data bursts).

### Look B: "Corporate Blue Glass"
*Use this for B2B ad-tech, explainer, and dashboard walkthroughs.*
*   **Palette:** `#020617` base + `#1d63ff`/`#70a6ff` accents. Cool, professional tones.
*   **Background:** `mono_dark` with subtle grid lines or shifting cyan haze.
*   **Typography:** Bold, sentence-case hero; medium body text. Compact UI labels.
*   **Motion Keywords:** `spatial_drift`, `glass_sheen`, `cursor_glide`. Minimalist float.
*   **Transitions:** `light_cone_zoom`, `gradient_blend` (seamless background shifts).

## 3. PROFESSIONAL RULES (CONCRETE NUMBERS)
*   **Spacing:** Minimum **8px** internal padding on all `card` and `chip` layers. Maintain **40px+** margin between headline and top edge.
*   **Timing:**
    *   Standard scene duration: **2.0s – 5.0s**.
    *   Text reveal duration: **1.2s** (linear to ease-out).
    *   Camera glide speed: **0.8x** normal playback (smooth, not frantic).
*   **Easing:** Default to **cubic-bezier(0.4, 0, 0.2, 1)** for floats; **step-start** for UI state changes.
*   **Blur Strategy:** Apply high blur (`blur_3d`) only to secondary rows or background blobs. Keep primary text sharp (no motion blur on text unless intentional speed effect).

## 4. MISTAKES TO AVOID
*   **Legibility Trap:** Do not place fine data text on cards when the camera is moving at >0.5 speed. Blur aggressively or reduce contrast if text becomes illegible during `fly_through`.
*   **Over-movement:** Avoid aggressive `spin` or `bounce` animations on primary UI elements in Look B (Corporate). Stick to `rise` or `pop`.
*   **Contrast Neglect:** In Look A, ensure secondary card text isn't washed out by the orange glow. Use semi-transparent overlays (`opacity: 0.8`) before adding text.
*   **Layout Clut

DOCUMENTARY / EDITORIAL COLLAGE STYLE (learned from 6 refs: crime-board title sequence, vintage typewriter dossier, Sony history doc, map with boats, cut-out person with doodles). Use for history, true-crime, biography, explainers, 'story of X'.
LOOK: a physical desk/wall feel: dark slate or concrete bg with vignette, ONE strong accent (blood red or lemon-yellow label) + warm paper tan; polaroid frames (white rrect + photo), torn paper cards, tape chips, pill date label with typewriter font. Photos black-and-white or sepia. Never glossy gradients here.
STRUCTURE: slow, 2-4 s per scene; each scene is ONE subject: big dated title (MAY / 1946 on a yellow label) -> portraits with name tapes -> objects. End on a short hard title (red, glow) after a flash.
MOTION: items drop in like placed on a table: pop + small rotation (-7..+7 deg), 0.2-0.5 s apart; tape/floor-plan lines draw by wipe; red string lines connect photos one by one; camera slowly pushes 1.0->1.08 and resets at each scene; typed text (chars step 0.04) for facts and dates; scene change = wipe or stripes transition, never random.
CUTOUT STYLE: a person cut out with a thick white outline on dark bg, small doodle icons (gear, pie chart, dollar notes) pop around the head with bounce - one icon per spoken idea.
SOUND (premium/viral): paper slide whoosh per item, soft thud on stamp/title, typewriter ticks while text types, riser into the final title, deep rumble drop on the red title; sparse, 1 sound per visible event.
