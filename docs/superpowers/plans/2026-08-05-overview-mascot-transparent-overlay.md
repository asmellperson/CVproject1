# Overview Mascot Transparent Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the rectangular looping overview video with a transparent, click-to-replay mascot overlay while keeping the banner title centered on one line.

**Architecture:** A focused `OverviewMascot` React component owns playback state and swaps to a transparent final-pose PNG when playback ends. A purpose-specific OpenCV/FFmpeg build script converts the supplied MP4 into a tightly framed VP9 WebM with alpha and the final-pose PNG; `HomeSection` only positions the component over the existing banner.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Node test runner, Python/OpenCV/NumPy for offline masking, FFmpeg/libvpx-vp9 for alpha encoding.

---

### Task 1: Lock the required banner and playback contract

**Files:**
- Modify: `unified_frontend/tests/overview-mascot-contract.test.mjs`
- Test: `unified_frontend/tests/overview-mascot-contract.test.mjs`

- [ ] **Step 1: Replace the old MP4/full-banner assertions with the new contract**

Assert that `OverviewMascot.tsx` exists and contains `useRef`, `useState`, `currentTime = 0`, `play()`, `onEnded`, `autoPlay`, `muted`, `playsInline`, no `loop` or controls, a WebM source, and a final-pose PNG. Assert that `HomeSection.tsx` renders `<OverviewMascot />`, keeps the title in a centered container, includes `whitespace-nowrap`, and no longer references `平台总览动画-蓝白版.mp4`.

- [ ] **Step 2: Run the contract test and verify RED**

Run: `node --test tests/overview-mascot-contract.test.mjs` from `unified_frontend`.

Expected: FAIL because `src/components/OverviewMascot.tsx` and the transparent media do not exist.

- [ ] **Step 3: Keep the failing output as the implementation baseline**

Do not weaken assertions to match the current full-banner looping video.

### Task 2: Build reproducible transparent mascot media

**Files:**
- Create: `unified_frontend/scripts/build-overview-mascot.py`
- Create: `unified_frontend/public/assets/overview/overview-mascot-alpha.webm`
- Create: `unified_frontend/public/assets/overview/overview-mascot-final.png`
- Modify: `.gitignore`

- [ ] **Step 1: Implement the offline converter**

The script accepts the source MP4 and output directory, decodes frames with OpenCV, estimates the neutral background from edge samples, builds foreground seeds from saturation/luminance/color-distance, runs GrabCut, retains components connected to strong colored subject pixels, removes neutral pixels below the subject silhouette, feathers the alpha edge, and recenters frames into a fixed transparent canvas. It writes lossless RGBA PNG frames to a temporary directory and invokes:

```bash
ffmpeg -framerate 30 -i frame-%04d.png \
  -c:v libvpx-vp9 -pix_fmt yuva420p -lossless 1 -an overview-mascot-alpha.webm
```

The last RGBA frame is also saved as `overview-mascot-final.png`. The temporary directory is automatically removed.

- [ ] **Step 2: Generate assets from the supplied source**

Run:

```bash
python3 scripts/build-overview-mascot.py \
  public/平台总览动画.mp4 \
  public/assets/overview
```

Expected: a VP9 WebM and RGBA PNG with no audio stream.

- [ ] **Step 3: Verify media metadata and transparency**

Run:

```bash
ffprobe -v error -show_entries stream=codec_name,pix_fmt:stream_tags=alpha_mode \
  -of default=noprint_wrappers=1 public/assets/overview/overview-mascot-alpha.webm
```

Expected: `codec_name=vp9` and `TAG:alpha_mode=1`.

- [ ] **Step 4: Inspect representative frames**

Decode first, middle, and final frames over a checkerboard/contact sheet. Confirm the black bars, pale background, ground line, shadow, and lower-right mark are absent while the mascot body, white armor, face, and visor remain.

### Task 3: Add the isolated playback component

**Files:**
- Create: `unified_frontend/src/components/OverviewMascot.tsx`
- Test: `unified_frontend/tests/overview-mascot-contract.test.mjs`

- [ ] **Step 1: Implement playback and final-pose state**

Create a button whose outer wrapper is `pointer-events-none absolute left-0 top-0 z-[4] h-full aspect-[600/544]`; make only the button `pointer-events-auto`. This keeps the media canvas as tall as the banner and derives its width from the generated asset. Render a static final PNG on mobile. On desktop render the WebM while `isPlaying` is true, set `isPlaying(false)` in `onEnded`, and show the final PNG otherwise. The click handler sets `currentTime = 0`, sets playing state, and calls `play()` after the video is visible.

- [ ] **Step 2: Preserve non-blocking input behavior**

Use a transparent button with an accessible label. Do not add controls, looping, fixed positioning, document listeners, or scroll handlers.

- [ ] **Step 3: Run the focused contract test and verify GREEN**

Run: `node --test tests/overview-mascot-contract.test.mjs` from `unified_frontend`.

Expected: all mascot contract tests pass.

### Task 4: Integrate without moving the centered title

**Files:**
- Modify: `unified_frontend/src/sections/HomeSection.tsx`
- Test: `unified_frontend/tests/overview-mascot-contract.test.mjs`

- [ ] **Step 1: Remove the full-banner looping video**

Delete the current `<video>` that covers the entire hero and references `平台总览动画-蓝白版.mp4`.

- [ ] **Step 2: Render the overlay and center content**

Import and render `<OverviewMascot />` as a direct child of the hero section. Change the hero content wrapper to full-width `justify-center text-center`, remove `md:pl-[340px]`, `lg:pl-[390px]`, and `2xl:pl-[620px]`, and add `whitespace-nowrap` plus a responsive `clamp()` font size to the title.

- [ ] **Step 3: Run the focused test again**

Run: `node --test tests/overview-mascot-contract.test.mjs` from `unified_frontend`.

Expected: all tests pass.

### Task 5: Full verification and handoff

**Files:**
- Verify all modified files and generated assets.

- [ ] **Step 1: Run frontend tests**

Run: `node --test tests/*.test.mjs` from `unified_frontend`.

Expected: zero failures.

- [ ] **Step 2: Run lint and production build**

Run: `npm run lint` and `npm run build` from `unified_frontend`.

Expected: both exit with code 0.

- [ ] **Step 3: Perform browser checks**

At desktop width, verify the 50%-opacity mascot is exactly as tall as the banner and its width follows the `600:544` media ratio while the title remains a centered single line. At less than 768px, verify the final-pose image uses the same height and aspect-ratio rule. Click the desktop mascot after playback ends and verify exactly one replay. Confirm the building remains visible and page buttons/scrolling still work.

- [ ] **Step 4: Review the final diff**

Run `git diff --check` and `git status --short`; confirm no unrelated files changed and report any remaining media-edge limitations.
