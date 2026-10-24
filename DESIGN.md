# Sunwai frontend design notes

## Direction

The interface treats a complaint as a case file that is assembled, stamped with source information and handed back to the person for review. The visual language uses a cool paper background, compact ink-colored controls, khaki folder details, violet proof marks and warm red for a near deadline or a blocker. Body text uses Mukta so English and Devanagari sit together evenly; Anek Latin supplies short display headings.

## Routes and flow

`/` is the story-first intake. It moves into `/case/[id]`, where a small fact check leads to the complaint ladder, proof source, editable draft and approval preview. The Agent tab shows a local fictional portal in mock mode and the live browser stream when the API supplies a URL. It ends at the review packet; only the separate “I submitted it” action records an acknowledgement number. The Timeline tab carries the wait date and next filing pack. `/sandbox/grievance` and `/sandbox/status` are clearly branded as fictional demos.

## Tokens and surfaces

The color and shape variables are declared at the top of `app/globals.css`. Inputs and controls have visible focus rings, compact borders and keyboard-sized targets. The default layout is light; the theme toggle stores a dark preference. At 650 px and below, the case workspace becomes a single-column tabbed view with a fixed mobile navigation bar.

## Motion and visuals

The hero keeps a CSS staircase illustration visible as the fallback. A procedural React Three Fiber scene loads after the first paint and only when the hero enters view; it uses simple folder and stair geometry, DOM labels and a slow drift. The Demo panel can select Full, Lite or Off; reduced motion and missing WebGL leave the static illustration in place. The review stop uses a brief CSS stamp landing animation. No downloaded models, textures or government marks are used.

The review packet, event feed and DOM ladder remain the readable source of truth. Canvas content is `aria-hidden`; the same important steps and facts appear in normal HTML. The scene uses a transparent background so it doesn’t cover controls or delay the intake form.

## Language and API

English and Hindi UI strings live in `messages/en.json` and `messages/hi.json`. The locale toggle persists in local storage. The local mock adapter implements the intake, case, plan, draft, approval preview, simulated agent outcomes, acknowledgement, demo clock and sandbox counters. Live mode calls the shared contract endpoints through `lib/api.ts` and checks core response shapes with Zod.

## Known frontend limits

The full WebGL experience is limited to the hero staircase. The ladder map, page flip, calendar and stamp are DOM/CSS visuals. Voice entry depends on browser speech recognition. Local mock cases and sandbox counters are browser-local; live integration depends on the separately implemented API and its CORS configuration.
