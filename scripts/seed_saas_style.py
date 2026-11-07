"""Seeds memory/ with the SaaS-promo AND documentary style guides + technique cards learned from two reference promos (Machina Sports, EzyCommunity).
Safe to run again: techniques are merged by name, the style guide is only written when no style guide exists yet (or --force)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mgl.memory import Memory

SG = """SAAS PRODUCT PROMO STYLE (learned from two real promos: Machina Sports 60s dark+orange, EzyCommunity 111s navy-violet). Use when the brief is a product/app/SaaS/service promo or explainer.
LOOK: near-black or deep navy-violet bg + soft glow blob + faint grid; ONE brand accent (orange or electric violet) + white; clean geometric sans (Poppins). Glass rrect panels, thin border, glow shadow. Product UI shown BIG (device/browser/card layers), never tiny.
RHYTHM: 1.5-4 s per beat, a new idea every beat, cut on the narration word. Hook in the first 1.5 s (question or number: 'What if just 430 customers...'). Order: hook -> problem -> logo reveal -> 3-5 feature beats (one headline + one UI each) -> proof/number -> price/benefit -> logo + CTA button held to the end.
MOTION: each beat = headline (blur/slide_up/wipe, words appear one by one) + UI panel arriving from depth (tilt/zoom/rise, camera push-in 1.0->1.1) + small chips/icons popping 0.15 s apart. Hero floats (float y 8-14). Panels leave by blur/zoom, never just vanish. Numbers count up. Prompt/search bars: typed text + cursor/arrow icon. Highlight the key word with accent colour or a pill. Big camera move + transition layer (wipe/flash) only on scene changes.
SCRIPT -> VISUAL: money/price -> count-up card + pricing cards; people/community -> avatar circles joined by lines; mobile app -> phone device; website/dashboard -> browser/laptop; speed/AI -> sparkle/orb logo + particles; feature list -> staggered chips/rrects; comparison -> two bars (You keep 77% vs 0%); steps -> numbered rrects; CTA -> button chip + brand.
SOUND (premium style): soft whoosh at scene changes, glass pop per chip/card, tick per counter step, key tap while text types, rumble thud on the hero headline, riser into the logo, shimmer hit + chime on logo and CTA. Quiet, sparse, one sound per visible event."""

T = [
 ("SaaS promo beat structure", "brief is a product/app promo", "Each 2-4 s beat: headline (blur or slide_up, reveal words step 0.25) + one big UI panel arriving with tilt/zoom/rise + 2-3 chips popping 0.15 s apart. Camera push-in 1.0->1.1 on every beat; hero floats y 10."),
 ("Hook question with big number", "opening line of a promo", "Beat 1 (0-2.5 s): plain dark bg + blob. One line 'What if just {n} customers': number in accent colour, bigger, count-up; words reveal step 0.2; then blur into a UI panel."),
 ("Tilted glass UI panel", "showing a dashboard, pricing or app screen", "card/device layer yaw -14..-18, scale 1.4, glass border + glow shadow; animate yaw to 0 and scale 1.4->1.5 over 2 s while camera pushes in; blur other panels behind (blur 6, opacity .4)."),
 ("Typed prompt / search bar", "script says search, ask, domain, AI prompt", "rrect pill w 900 h 90 glass, search icon left, text reveal chars step 0.05, arrow_up icon pops when typing ends, then the bar slides up and the result panel zooms in."),
 ("People joined by lines (community)", "customers, members, community, team", "6 circle avatars in a row, a logo chip above, line layers from logo to each avatar (wipe), avatars pop 0.12 s apart, a price label ($49/mo) pops over the first one."),
 ("Count-up money card", "revenue, price, savings, results", "card kind custom big_text '${n}' with keys number 0->target ease out over 1.8 s, accent header, glow shadow; a green chip '+x%' pops when the count ends; chime."),
 ("Two-bar comparison", "you keep vs platform cost, before vs after", "two progress bars or bar chart: left 'You Keep' 77% grows (grow dur 1.2), right 'Platform cost' 0% stays empty; pill labels above each; accent colour on the winner."),
 ("Pricing cards row", "plans, tiers, offer", "3 cards side by side, middle one scale 1.12 with accent border + 'Best value' chip; rise in 0.15 s apart; then a 'Buy now' rrect pulses (scale 1->1.05 keys) while the camera pushes in."),
 ("Phone fan mockup", "mobile app, white-label app", "3 phone devices fanned (rot -12, 0, 12; centre bigger), app icon chip pops on the centre one; slow float; brand-colour blob behind."),
 ("Feature list stagger", "several features or steps", "Headline left (size 90), 4-5 chips/rrects right, slide_left in 0.2 s apart; each gets an accent border in turn while its line is spoken; others dim to opacity .5."),
 ("Sparkle/orb logo sting", "logo reveal, AI, brand moment", "big accent circle/icon pops with bounce, glow shadow 60, particles burst, ring scales 1->2 and fades; brand letters rise below; riser sound ends exactly on the pop."),
 ("Blur-through scene transition", "between product beats", "Old scene ends blur 0->10 + zoom out 0.4 s while the new one starts blur 10->0 zooming in; add a flash transition 0.3 s only on the biggest change (into the logo)."),
 ("Closing CTA hold", "last 2-3 s of any promo", "Logo + one line + accent button chip ('Book a demo today') centred, pop in then float y 6; nothing leaves; soft glow behind; shimmer hit + chime on the button."),
 ("Script word to visual mapper", "always, before designing", "Read the script sentence by sentence: pick ONE visual from its key noun (money->count card, people->avatars, app->phone, site->browser, speed->sparkle, list->chips, versus->two bars); time it to that sentence; text 3-6 words."),
]

DOC_SG = """DOCUMENTARY / EDITORIAL COLLAGE STYLE (learned from 6 refs: crime-board title sequence, vintage typewriter dossier, Sony history doc, map with boats, cut-out person with doodles). Use for history, true-crime, biography, explainers, 'story of X'.
LOOK: a physical desk/wall feel: dark slate or concrete bg with vignette, ONE strong accent (blood red or lemon-yellow label) + warm paper tan; polaroid frames (white rrect + photo), torn paper cards, tape chips, pill date label with typewriter font. Photos black-and-white or sepia. Never glossy gradients here.
STRUCTURE: slow, 2-4 s per scene; each scene is ONE subject: big dated title (MAY / 1946 on a yellow label) -> portraits with name tapes -> objects. End on a short hard title (red, glow) after a flash.
MOTION: items drop in like placed on a table: pop + small rotation (-7..+7 deg), 0.2-0.5 s apart; tape/floor-plan lines draw by wipe; red string lines connect photos one by one; camera slowly pushes 1.0->1.08 and resets at each scene; typed text (chars step 0.04) for facts and dates; scene change = wipe or stripes transition, never random.
CUTOUT STYLE: a person cut out with a thick white outline on dark bg, small doodle icons (gear, pie chart, dollar notes) pop around the head with bounce - one icon per spoken idea.
SOUND (premium/viral): paper slide whoosh per item, soft thud on stamp/title, typewriter ticks while text types, riser into the final title, deep rumble drop on the red title; sparse, 1 sound per visible event."""
DOC_T = [
 ("Evidence board with red string", "crime, mystery, investigation, who is behind", "polaroid rrects at 5 spots rot +-5, pop 0.18 s apart; then line layers (red, w 4) wipe between pairs 0.25 s apart; flash transition red; final red title with blur-in + glow."),
 ("Floor-plan tape lines", "case file, scene, planning", "off-white line layers w 6 forming open rooms, drawn by wipe (right/down/up); props (cards, chips) sit inside them; camera push 1.06 per scene."),
 ("Typewriter dossier card", "person profile, biography, name + role", "tan paper rrect slides in from the side (rot 1.5); name bold 74 wipe-in; role italic with chars reveal 0.04; date pills (dark rrect + light bold text) pop last."),
 ("Dated history title", "year, date, era, 'in May 1946'", "huge red month (bold_italic 230, zoom in), yellow-green label rrect rot -1 with year 100 popping under it, two polaroid portraits with name text rot +-7 land after."),
 ("Object parade on blue", "products, inventions, list of things", "ocean/blue bg with particles; one emoji/image per idea (210 px) bounces in 0.5 s apart, float y 14 phase offset; a one-line caption by words; fade them all before the next headline."),
 ("Cut-out with doodle icons", "business person, founder, money talk", "person image with white outline centred; gear/pie/dollar icons pop with bounce one per idea around the head; slight float; dark paper-texture bg."),
 ("Tilt-shift map scene", "journey, trade route, expansion", "map image bg blurred top/bottom (vignette), small boat/icon images drifting along an orange dashed line (line layer wipe), red circle ring marking the place; slow camera push."),
 ("Paper scene swap", "between documentary scenes", "wipe transition (dark colour 0.5 s) at the cut; the new paper card rises (slide up 0.8 s) while old items fade; keep the same polaroid position so the eye stays."),
]
def seed(root='.', force=False):
    m = Memory(root); assert len(SG) <= 2600, len(SG)
    assert len(DOC_SG) <= 1500, len(DOC_SG)
    full = SG + '\n\n' + DOC_SG
    if force or not m.style_guide(): m.write_style_guide(full)
    elif 'DOCUMENTARY / EDITORIAL' not in m.style_guide(): m.write_style_guide(m.style_guide().rstrip() + '\n\n' + DOC_SG)
    new = 0
    for name, when, how in T:
        assert len(how) <= 320, (name, len(how))
        if m.add_technique({'name': name, 'when': when, 'how': how}, source='ref:Machina+EzyCommunity'): new += 1
    for t in m.notebook['techniques']:
        if t.get('source', '').startswith('ref:Machina'): t['weight'] = 5
    for name, when, how in DOC_T:
        assert len(how) <= 320, (name, len(how))
        if m.add_technique({'name': name, 'when': when, 'how': how}, source='ref:Documentary'): new += 1
    for t in m.notebook['techniques']:
        if t.get('source', '') == 'ref:Documentary': t['weight'] = 4
    m.save(); return new

if __name__ == '__main__':
    print('techniques added:', seed(force='--force' in sys.argv))
