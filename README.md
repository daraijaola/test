# Citrus Jelly

An interactive gummy citrus slice: a tetrahedral soft body simulated in JavaScript and
drawn with WebGPU and WGSL. Grab it anywhere, stretch it, let go.

Open `index.html` in a browser with WebGPU (current Chrome, Edge, Safari or Firefox).
It is one self-contained file and makes no network requests.

## Layout

| Path | What it is |
| --- | --- |
| `index.html` | The built page. Generated; do not edit by hand. |
| `src/mesh.js` | Procedural half-disc: particles, tetrahedra, flesh / pith / rind zones. |
| `src/sim.js` | Soft body: XPBD constraints at a fixed 1/600 s step, stretch limits, volume preservation, ground contact, sticky base, grabs. |
| `src/render.js` | WebGPU renderer: ray-marched translucent material, refraction, contact shadow, mesh overlay, three palettes. |
| `src/ui.js`, `src/page.html`, `src/styles.css`, `src/fonts.css` | The page chrome and embedded fonts. |
| `src/main.js` | Frame loop, picking and dragging, camera, quality scaling, failure handling. |
| `tools/build.cjs` | Bundles `src/` into `index.html`. No dependencies. |

## Build and test

```sh
node tools/build.cjs          # src/ -> index.html
node tests/sim.test.cjs       # physics, in Node (about 100 s)
node tests/e2e.test.cjs       # the page in headless Chromium
node tests/app.test.cjs       # pixels, input, quality scaling, failure paths
node tests/filmstrip.cjs all  # contact sheets of scripted interactions, for judging motion
```

The browser tests need Playwright with Chromium and run WebGPU on a software
rasteriser, so they say nothing about frame rate on real hardware.

## Controls

Drag the slice to stretch it; drag empty space to turn the view. `Space` pauses,
`R` resets, `N` gives it a nudge. Append `?quality=full`, `low` or `auto` to the URL
to pin or release the automatic picture-quality scaling.
