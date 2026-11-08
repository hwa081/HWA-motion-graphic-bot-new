## Free local AI backup (Qwen3.5 4B on the runner)
- Set the repository variable `LOCAL_AI` to `on` (or type `on` in Settings -> Options -> "Free local AI backup"): the workflow installs Ollama on the GitHub runner, downloads `qwen3.5:4b` (about 3 GB, `LOCAL_AI_MODEL` changes the model) and the bot adds "Local Qwen (free)" as the very last AI. It is used only when every other AI failed, it never takes the lead, it is skipped for requests with pictures (Gemini does those), and its prompt is always shortened (about 11k tokens). Never runs out of quota, but slow on 4 CPU cores. If Ollama cannot be installed the step is skipped (`continue-on-error`) and nothing else changes.
- Fixed a random test (the 413 test depended on the key rotation start).

## Auto-continue switch + a proper "making your video" card
- **Top bar switch "Auto-continue"**: when ON, a video that stops for any reason (AI quota, network, GitHub cancelled it ...) is continued by itself after a wait of 1:00, 1:45, 2:30 ... (at most 10 min), again and again until it is finished (safety stop after 30 automatic tries). It always goes on from the saved work. A video you stopped yourself with Stop is never restarted. A failed tile shows "Auto-continue in m:ss" and a "Continue now" button. Works while the Studio page is open (the page does the restarting). The switch is remembered in the browser.
- New progress card: run timer, big percent with a moving bar, 7 step marks, what the current step means, long-video part marks ("Part 4 of 10"), a grey line with what the AI layer is doing now (asking Groq / waiting / skipping an AI), time left, and "try N · last stop: ..." after automatic retries. The card is bigger and aligned to the top.
- `mgl/progress.py` now also sends `part` and `note` to the page.

## Stop button + no more wasted time on dead AIs
- Studio page: every running / waiting video has a **Stop** button. It cancels the GitHub run (force-cancel if needed); the saved parts stay and Continue goes on later. Needs the token's "Actions: Read and write".
- A provider that has no access or no credits (HTTP 401/402/403, "no credits remaining", Gemini 403 "free tier not available for this project") is skipped for the rest of the run at once - no retries, and Gemini does not try its other models of that key.
- HTTP 413 "request too large" (Groq free tier: 7-8k tokens per minute): the bot shortens the prompt (drops the working examples, then the memory block) and retries once; the learned limit is remembered so later requests are shortened right away. If it still does not fit, that AI rests for an hour and the next one takes over.

## Free-quota proof AI layer (no more 46-minute waits)
- A daily Gemini quota 429 ("PerDay" / free_tier) is recognised: the model is skipped at once for 3 hours, no waiting; a key whose models are all spent fails instantly ("quota") so the next key / AI takes over. Per-minute 429 still waits as before.
- Models answering 404 "no longer available" (e.g. gemini-2.5-flash for new users) are dropped for the rest of the run.
- Several Gemini keys: paste them separated by commas in Settings -> Gemini (the secret holds them all). They are used in turn (their quotas add up), a dead key costs nothing after the first try, parallel runs / lanes start on different keys. `AI_SPREAD=false` switches this off. Other AIs (Groq, OpenRouter, Ollama-compatible URL ...) stay the fallback and lead once they had to step in.
- The Settings test checks every pasted Gemini key and reports "N of M keys work".
- Long videos in fast mode: no AI quality-fix rounds per part (1 request per part); quality mode 1 round (was 2).

## Merge: studio_2 features + my line (voice-over, storyboard, chunked render, pen tool, merge_json)
- Brought in from studio_2: `mgl/voice.py` (voice-over mode), `mgl/storyboard.py` (one-picture storyboard + Approve), `mgl/pen.py` + `PEN_TOOL.md` + `--mode pen-import` (spec `pen` layers), chunked "never lose work" render, `scripts/merge_json.py` (replaces my merge_conflict.py), their Studio page (day groups, select + delete, 2 lanes, Voice button, Storyboard chip).
- Kept from my line: premium SFX (`mgl/sound_pro.py`), SaaS + documentary style guides and 22 techniques, native `.wfp` text fix + richer converter + user-verified pen clips, speed timing log, the `.wfp native` chip, and "MP4 off = the video is NOT rendered" when no chosen file needs it (their MP4-off still rendered it).
- `pen` layers of a design are now converted to real Filmora pen clips by my native converter (anchors with Bezier handles, fill, stroke, draw-on trim).
- Page: new chip `.wfp native` next to .wfp / FCPXML / XML.

## Documentary / editorial-collage style learned
- Studied 6 reference videos (crime-board title, typewriter dossier, Sony history doc, tilt-shift map, cut-out person). Added a documentary style guide + 8 technique cards to memory (seed script now seeds both styles, 22 techniques; style guide cap 2600 -> 4200 chars).
- Three new example designs: `examples/documentary_case_board.json` (evidence board + red string + red title), `documentary_dossier.json` (typewriter paper, polaroids, date pills), `documentary_history.json` (dated title + object parade).

## SaaS-promo style learned from reference videos
- `memory/style_guide.md` + 14 technique cards (`memory/notebook.json`) written from a frame-by-frame study of two real SaaS promos: look, rhythm, motion, script-word -> visual mapping, sound plan. Every AI prompt now carries them (style guide cap 1800 -> 2600 chars). `scripts/seed_saas_style.py` re-creates them anywhere.

## Premium SFX
- New `mgl/sound_pro.py`: riser, whoosh, double clack, rumble drop, shimmer hit, ticks, thud, pop - procedural, spectrum-matched to a pro SFX pack (no recorded audio). Used by the `premium` style and exported in the SFX pack as `pro_*.wav`.

# Motion Graphic Bot - merged version

## Native .wfp text fix
- Filmora draws text at FontSize x TextScale (2.32) pixels, so every native text was about 2.3 times too big. Sizes are now divided by TextScale; the text box is set from the real text width.
- Lines (\n) become separate text layers, every line is shrunk to fit the frame (or its button / card / chart slot), left / right anchors become the centre Filmora needs.

## Speed log, 2 parallel videos, day groups, bulk delete, richer native .wfp
- mgl/timing.py: every run prints `[time] ...` and writes a "Where the time went" table (AI requests, rate-limit waiting, render, files) into report.md and out/timing.json; the published entry carries a short `timing`. Use it to see why a video is slow before guessing.
- Parallel: the workflow has an input `slot` (1 or 2) and the concurrency group is per lane (`motion-bot-lane-<slot>`); the page runs 2 videos together and queues a third. scripts/commit_memory.sh now fetches + rebases and merges conflicting files (scripts/merge_conflict.py: index.json by id, memory lists/dicts) instead of failing.
- Page: the grid is grouped by day (Today / Yesterday / Monday . 3 Nov ...), each day can be hidden or shown (remembered); projects still filter. Select mode (check icon in the top bar): tick several videos or a whole day, then Move to trash; in Trash: Restore or Delete forever (asks twice; removes the files from the repository too).
- Native .wfp: cards, chips, bar / line / donut charts, progress bars and rings, icons, device frames (phone, laptop, browser) and blobs now become editable layers. Group animations are fade + move (scale / rotation of a whole group is not applied); still skipped: image, emoji, particles, grid, transition.

## MP4 on/off + native .wfp from the AI design
- Page: the MP4 chip is a real switch now (default on). New chip ".wfp native". Formats sent to the bot carry the tokens `nomp4` and `native`.
- run.py: `nomp4` + only formats that do not need a video (native, srt) = the video is NOT rendered. If a chosen format needs the video (wfp, xml, fcpxml, gif ...), it is rendered anyway. Code Studio and videos over 60 s ignore `nomp4`.
- mgl/native_wfp.py: `spec_to_scene()` turns the AI design into a native Filmora scene: text, rounded boxes (Bezier), circles, lines become editable layers; icons, emoji, images, cards, chips, charts, devices, particles are skipped. Easing becomes linear, the background becomes one flat colour. 16:9 only.
- publish.py: a run without MP4 is published as kind `files` (tile "no MP4 · n files"); the viewer lists its files.

## Native Filmora: free pen shapes
- mgl/native_wfp.py: new layer type `pen` (polygon / polyline from points, fill + second colour, stroke, drop shadow, trim draw-on, transform + opacity keyframes), cloned from a real Filmora project (mgl/templates/pen_sample.wfp). `ngon()` makes circles / polygons / stars. `pen_demo_scene()` = demo. Confirmed by the user: the demo opens and plays in Filmora.
- Bezier curves (from the user's second sample, mgl/templates/pen_curves_sample.wfp): a point may carry `left_ctrl_point` (type 1, incoming) and `right_ctrl_point` (type 2, outgoing) with absolute frame coordinates. Layer points: (x, y) corner or (x, y, left, right). Helpers `circle()` (true round, 4 points) and `smooth()` (Catmull-Rom curve through points, open or closed).
- Not known yet: whether fillType 1 is solid or gradient; the rotation pivot.

## Studio v2: progress, projects, files, Draft/Final, long videos, resume, Activity
### Studio v2 - "slow is fine, failing is not"
- AI: patient retries (429 / 5xx / network, up to `AI_PATIENCE_MIN`, default 12 min), model and provider fallback.
- A design with a few broken layers is repaired (broken layers dropped); if the AI never gives a usable design, a simple title video is made instead of failing.
- Render: parallel -> one worker -> light encoder retries; a frame that errors repeats the previous frame.
- If a run still stops, `error_report.md` is published: the tile shows the reason and Continue resumes from the saved work.
- mgl/progress.py: reads what the bot prints (stage, %, frames, ETA) and writes progress/<job>.json on branch bot-progress; page shows bar, stage n/7, time left.
- render.py: parallel frame rendering (same pixels as one worker, tested), DEFAULTS for draft (half size, 15 fps, ultrafast).
- run.py: --project --quality draft|final --parent --resume; draft makes only light files, heavy editor files at Final; publish lists files (wfp, xml, fcpxml, srt, gif ...), video_name, project, quality, parent, formats.
- mgl/work.py: checkpoints work/<key>.json (repo + bot-progress branch); single videos save the design before rendering, so a stop costs no AI requests.
- mgl/longform.py: 61-600 s videos part by part (outline, per-part design saved at once, style anchor from part 1, render, sound, join); stops cleanly on quota/time and continues with the first missing part.
- Page: projects menu, file chips + Draft/Final in the prompt bar, 30 s - 5 min buttons, Continue/Log/Remove on stopped jobs, Activity view, ideas, Drafts / Long videos filters, files download in the viewer.
- Workflow: inputs project, quality, parent, resume; PROGRESS_TOKEN; timeout 345 min; ffmpeg install skipped when present.
- Tests: page 25 pass; bot tests for progress, parallel render, draft/final publish, long video + resume.

## Studio page (GitHub Pages) - Google Flow style front end
- docs/: static site (index.html, css/studio.css, js/{app,crypto,gh,settings,jobs,library}.js, vendor/nacl-fast.min.js, ARCHITECTURE.md). No editor (cancelled).
- Settings page: GitHub token + connection check, Gemini / Pixabay / Pexels keys (tested, then encrypted in-browser and saved as GitHub Secrets), any number of OpenAI-compatible AI providers (AI_KEY_<ID> secrets), default AI + fallback + bot options as repo Variables, "test all keys in the cloud" (mode checks).
- Generate: prompt bar with image/video, ratio, duration, x1-x4, model; attachments uploaded to the repo; workflow_dispatch; client-side queue; progress tiles; results shown from outputs/index.json; viewer with report, stars/feedback, trash, use-as-reference.
- Library (designs, techniques, lessons, wishes) and Tools (compare, remix, study, learn, evolve) read memory/*.json.
- mgl/llm.py: multi-provider LLM layer with fallback; mgl/publish.py: outputs/ publishing; run.py modes checks; workflow run-name + inputs ai/job.
- Tests: tests/test_studio_ui.py (Playwright + fake GitHub, 18 pass), test_all.py extended.

## Smart upgrade (compare, remix, director, guard, notebook)
- mgl/compare.py: example video vs yours, measured (palette, pacing, cuts, motion, brightness, density, layout) -> score + concrete gaps + side-by-side PNG; optional AI judgement; learns lessons + techniques.
- mgl/remix.py: fingerprints, originality gate (too close to a library/memory design or copied text -> fix), remix recipes (borrow 2-3 ideas, mutate what the last videos used).
- mgl/planner.py: director's plan before the spec (concept, signature idea, scenes, wishes). Off by default in agent.run_agent(plan=False), on in run.py (PLAN variable).
- mgl/judge.py: quality number + Best(); revisions that make the video worse are thrown away (regression guard).
- mgl/study.py + memory/notebook.json: techniques (from references, compare, studied text/URL) and a wishlist; modes compare, remix, study, evolve.
- agent.py: with a reference video the bot compares itself (no quota) and fixes towards it; compare.md / compare.png in the output.
- Tests: 12 new, all pass. 3 old tests need resvg-py (SVG renderer) - fail only where it is not installed.

Is version mein dono zips ek ho gaye hain:
- Code Studio (code mode: scene.py likhna, sandbox, preview, QA, custom effects)
- Filmora .wfp / FCPXML / XML export, .wfp lighten (level 1-3), srt/gif/webm/poster/frames
- Sound (ui / kinetic / music), design library (116 ready designs + design_library.pdf), kinetic typography

Tests: 51 pass, 0 fail (clean environment, nakli Gemini server).
Abhi tak asli Gemini, asli Filmora aur asli GitHub Actions par test nahi hua.
Filmora .wfp: media type (audio ke saath 8, bina audio 2), thumb.fsthumb, ID format, key order, zip permissions asli file jaise hain.

## Native Filmora export (mode: native)
- mgl/native_wfp.py: rectangles + text as real editable Filmora layers, cloned from a real Filmora project (mgl/templates/native_sample.wfp).
- Metadata policy: only project name and save path change (tested to open). Duration sync (project length = scene length) is on by default; tested to open.
- Older video-import .wfp export did not open in Filmora; use native mode for Filmora projects.

### Viral SFX style
- New sound style `viral` (now the default): editor-style effects (dark gravel hit, snapshot woosh, camera shutter / multiple shuttle, gone fast, airy slice, bass drop, noise riser, tape stop, sparkle, rewind), no music, placed from the plan (cuts, hero words, images, exits). Page: sound style dropdown next to the Sound checkbox. The SFX pack now also contains the 11 viral sounds.

### Premium UI SFX (default)
- New sound style `premium`, now the default: soft warm app sounds (taps, glass pings in one key, airy whooshes, deep soft thuds, chime, bloom). Everything is low-passed (no energy above ~4 kHz), rounded attacks, quieter mix. `viral` stays as the punchy option.
- Premium: text now sounds like soft typing (a key per letter/word, a short flurry for headlines); the bubble pop is only used for popups (chips, cards, icons, emoji).
- Premium placement v2: typing keys only where text really types in (letter/word reveal); headlines that blur/slide/wipe/pop get a soft whoosh, the one hero headline a soft thud; cards, chips, icons and emoji get the bubble pop; scene changes get a soft whoosh; the bloom marks the closing headline.
- `sfx_pack/` folder: your own sound files are used by name in the premium / viral styles.
- Typing sync: with a typing clip in sfx_pack (premium style) text types exactly on the key hits (reveal `times` now also work for chars / letters); typing_6 from the sample video is included.

### Speed, order and parallel runs
- Fast / Quality switch in the prompt bar (default Fast): 1 AI request, no director plan, no AI review, small Gemini thinking budget (`GEMINI_THINKING`, workflow input `speed`). Quality keeps plan + review.
- Page: videos are grouped by day (In progress, Today, Yesterday, Monday ...) and each day can be hidden / shown; Select mode (tick button) picks several videos: move to trash, restore, delete forever (files removed from the repository).
- 2 videos run together: workflow input `slot` (1 / 2), concurrency group per slot; `scripts/commit_memory.sh` rebases and MERGES `outputs/index.json` and memory JSON when both runs save at the same time (`scripts/merge_json.py`).

## Pen tool
- mgl/pen.py: new `pen` layer (bezier path, draw-on trim, fill/gradient/glow/shadow), learned from two Filmora pen projects. Import `--mode pen-import`, export as editable Filmora pen clips (native mode). See PEN_TOOL.md.

## Never lose work, storyboard, MP4 switch
- render.py: a video is made in pieces of ~4 s; each finished piece is saved in work/<key>_render/ (committed even if the run fails). A retry or a new run skips finished pieces and continues at the exact piece. Each piece has its own retry chain (parallel -> one worker -> light encoder).
- mgl/storyboard.py + run.py `--storyboard ask|approved|off`: the bot analyzes the finished design, shows ALL scenes as ONE picture (outputs/<id>/storyboard.png) and stops. The page tile "Storyboard" has Approve (the video is made from the saved design, no new AI work), Make a different storyboard, Discard. Videos up to 60 s; longer ones skip the storyboard.
- Page: MP4 chip can be switched off (formats get `nomp4`: only the chosen .wfp / FCPXML / XML are kept, always Final); Storyboard chip; SRT and GIF options removed from the page.

## Voice-over mode
- mgl/voice.py: attach an audio file (mp3/wav/m4a/aac/ogg/flac, up to 10 min). The AI listens and writes the narration sentence by sentence (language, role, key words, times); scene cuts are moved into real pauses of the voice. Without an AI answer the pauses alone make the scenes.
- The video is exactly as long as the voice; each sentence = one scene; key words/numbers appear when spoken; after the design, cuts and layer starts snap to the sentence starts; the voice is loudness-normalised and mixed in, sound effects duck under it.
- Long voice-overs (over 60 s) are made in parts at sentence boundaries (same saved-part resume as long videos).
- Page: "Voice" attach button (length read in the browser, no text needed). Storyboard tiles show the spoken sentence under each scene.
