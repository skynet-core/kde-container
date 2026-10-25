# Diagrams: sources and rendering

[Technical guide](../README.md)

The guide embeds SVG diagrams so it remains readable in Markdown viewers that do
not support Mermaid. Each SVG has an editable `.mmd` source beside it. You do not
need Node.js, Chromium or a Mermaid plugin just to read the checked-in diagrams.

## Diagram index

| Diagram | Subject | Source | SVG |
| --- | --- | --- | --- |
| Architecture | Shared kernel, container services and display destinations | [Mermaid](architecture.mmd) | [Image](architecture.svg) |
| Build stages | Inheritance versus copied build artifacts | [Mermaid](build-stages.mmd) | [Image](build-stages.svg) |
| Boot | Init modules, `exec`, PID 1 and target activation | [Mermaid](boot.mmd) | [Image](boot.svg) |
| Mode selection | Host transport, requested backend and nested validation | [Mermaid](mode-selection.mmd) | [Image](mode-selection.svg) |
| Service order | Wayland web project's service ordering | [Mermaid](service-order.mmd) | [Image](service-order.svg) |
| Identities | Rootful Docker versus rootless Podman mapping | [Mermaid](identities.mmd) | [Image](identities.svg) |
| Mounts | Host sockets/cookies/files versus private container paths | [Mermaid](mounts.mmd) | [Image](mounts.svg) |
| Nested | Four combinations of desktop backend and host transport | [Mermaid](nested.mmd) | [Image](nested.svg) |
| Video | Wayland/X11 capture and direct/web transport | [Mermaid](remote-video.mmd) | [Image](remote-video.svg) |
| Input | Client events through the correct desktop input path | [Mermaid](remote-input.mmd) | [Image](remote-input.svg) |
| RFB handshake | Negotiation, authentication, pixels and input | [Mermaid](rfb-handshake.mmd) | [Image](rfb-handshake.svg) |
| UI test | Screenshot-based drag and UI save through a host file mount | [Mermaid](ui-test.mmd) | [Image](ui-test.svg) |

## Reading the arrows

Each chapter explains its figure's meaning. In particular:

- Build diagrams use solid `FROM` arrows for inheritance and dashed `COPY` arrows
  for selected artifacts.
- The service-order diagram shows ordering between already-requested units; it
  does not imply that `After=` activates a unit.
- Pixel diagrams show content traveling outward; input has its own inward path.
- The identity diagram is a conceptual host-ID mapping, not literal output of a
  potentially nested `/proc/.../uid_map` read.
- Sequence diagrams read from top to bottom. Participants are columns, and arrows
  represent messages/actions between them.

The figures intentionally omit unrelated distribution units and low-level engine
implementation details. The linked source and explanatory text provide the scope.

## Render one diagram

These commands use Node.js 22.13.0 or newer, npm, an installed Chromium executable, and the pinned
[Mermaid CLI](https://github.com/mermaid-js/mermaid-cli) version used for this guide.
Run them from the repository root. Substitute the correct browser path on your
machine if it is not `/usr/bin/chromium`.

```bash
# HOST: use the system browser instead of downloading Puppeteer's own browser.
export PUPPETEER_SKIP_DOWNLOAD=true
export PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# HOST: npm obtains/caches the selected CLI; mmdc renders the text source to SVG.
npm exec --yes --package=@mermaid-js/mermaid-cli@12.0.0 -- mmdc \
  -i docs/diagrams/architecture.mmd \
  -o docs/diagrams/architecture.svg \
  -c docs/diagrams/config.json -b white --size 1600
```

`config.json` selects a neutral theme and SVG text labels. White backgrounds retain
contrast when the same figure is viewed in light or dark Markdown readers. SVG is
a vector format, so the exported figures remain zoomable.

## Render all diagrams

```bash
# HOST: keep the browser environment variables from the previous example.
# Parentheses create a subshell: exit 1 stops this batch without closing your terminal.
(
  for diagram_source in docs/diagrams/*.mmd; do
    # Strip the .mmd suffix and append .svg for the matching output filename.
    diagram_svg="${diagram_source%.mmd}.svg"
    npm exec --yes --package=@mermaid-js/mermaid-cli@12.0.0 -- mmdc \
      -i "$diagram_source" -o "$diagram_svg" \
      -c docs/diagrams/config.json -b white --size 1600 || exit 1
  done
)
```

A parse error or rendering failure should fail the loop. After changing a source,
open its SVG and inspect long labels, arrows and the diagram's meaning; syntax
validation alone cannot establish that a schematic is technically correct.

For a raster preview without adding a PNG to the repository:

```bash
# HOST: render the same source to a temporary PNG for visual review.
npm exec --yes --package=@mermaid-js/mermaid-cli@12.0.0 -- mmdc \
  -i docs/diagrams/architecture.mmd -o /tmp/plasma6-architecture.png \
  -c docs/diagrams/config.json -b white --size 1600
```

These tools belong to documentation maintenance. They are not installed into or
needed by the Plasma runtime image.
