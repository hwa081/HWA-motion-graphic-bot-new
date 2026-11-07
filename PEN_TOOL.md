# Pen tool (Filmora style) - what the bot learned

Learned from your two Filmora projects: `pen_demo2.wfp` and `ai_to_native_kinetic_typography.wfp`.

## How Filmora stores a pen layer
- A pen layer is a clip with `serviceType: "pen"`. Its effect chain: `path` (the points), `path_stroke`, `path_fill`, `path_trim`, `path_dropshadow`, plus `transform`.
- Points: `value_x`, `value_y` are 0..1 of the canvas. A smooth point also has `left_ctrl_point` and `right_ctrl_point` (bezier handles, also 0..1). `is_closed` = closed shape.
- Stroke: colour, `lineSize`, alpha, round caps. Fill: flat or gradient (`colorStart` -> `colorEnd`), alpha, blur. Shadow: colour, distance, blur, alpha.
- The "line draws itself" effect = keyframes on `path_trim` -> `end` from 0 to 100.
- Scale and rotation keyframes turn around the canvas centre; opacity keyframes live in the clip's `pipBuf`.
- Units: clip times are 1/10,000,000 s, colours are BGR integers, keyframe times inside effects are seconds.

## What the bot can do now
1. **pen layer in any video** (`"type": "pen"`, see LIBRARY.md): bezier shapes and curves that draw themselves, fill, gradient, glow, shadow. The AI is told about it and uses it for logo marks, underlines, arrows, doodles.
2. **Import**: `python run.py --mode pen-import --files my_project.wfp` turns every pen layer of a Filmora project into a bot spec (`outputs/<name>_pen_spec.json`).
3. **Export**: `--mode native --files scene.json` writes pen layers as real, editable Filmora pen clips (type `pen`, same fields as the spec layer).

Not verified: opening the exported .wfp inside Filmora (only the structure was checked and read back by the bot).
