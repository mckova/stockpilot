---
name: Stockpilot
colors:
  canvas: "#e8e9e5"
  surface: "#f6f6f3"
  raised: "#ffffff"
  ink: "#17191b"
  ink-soft: "#50565c"
  ink-faint: "#7b8187"
  signal: "#f0b323"
  rail: "#1d3a2f"
  ok: "#2c6a3a"
  bad: "#b3261e"
typography:
  sans: "Archivo Variable (width 100 to 125)"
  mono: "IBM Plex Mono 400/500"
rounded:
  control: 3px
  panel: 6px
---

# Stockpilot design

## Overview

Stockpilot is an operations tool for the people who run a warehouse and the
stores it feeds: shift managers and clerks. The interface borrows its voice from
the warehouse floor itself: printed shelf labels, delivery notes, dispatch
slips. It should read as a working instrument, not a marketing page.

Dial: ENERGY 2 / RHYTHM 2 / MOTION 2. Calm, dense, ruled; motion only where
something actually changes.

Identity motif:

- **Printed-label voice.** SKUs, lot numbers, document numbers and quantities
  are set in mono. Status is a small square sticker, never a pill.
- **The bin gauge.** Stock against its reorder rule: a thin bar for the
  quantity, a solid notch at the minimum, a hairline at the maximum. Amber when
  below the minimum. It appears wherever a quantity has a rule behind it.
- **Slips.** Anything the AI planner proposes is a slip with a coloured top
  edge: amber while it waits for a signature, green once signed, grey when
  rejected.

## Colors

- Canvas, surface and raised white carry the layout. Ink is near black, with two
  softer steps for secondary and tertiary text.
- **Signal amber is reserved for one meaning: a person needs to act.** Items
  below their minimum, proposals waiting for sign-off, the primary action on a
  day that has alerts. If amber appears for decoration, it is a bug.
- The forest rail holds navigation and nothing else.
- Green and red mean done and wrong. They are never used as accents.
- No gradients, no glow, no glass.

## Typography

- Archivo, using its width axis: wider and uppercase for labels and table
  headers, normal width for reading text.
- IBM Plex Mono for every code and every number that a person compares across
  rows. Numbers are tabular and right aligned.
- Page titles are noun phrases. Subtitles are a single line of ten words or
  fewer. Chart titles are the question the chart answers.

## Layout

- App pages: page head with a bottom rule, then the work. Totals are a footnote,
  not a row of metric cards.
- The Today page is a worklist: what needs a person, with the action on the row.
  Charts sit beside it and answer one question each.
- The front page is the product's own surface, pinned while the visitor scrolls
  through one simulated morning (07:40 to 11:22). Every number on it is
  computed in the browser from a small data set; the scroll position only picks
  the step.
- Phones get their own composition: the rail becomes a top bar with a
  horizontally scrolling nav, worklist rows stack, and the front page shows only
  the pane that changes.

## Components

- Buttons: ink for the primary action, amber only when the action resolves an
  alert, ghost for everything else. Pressed state moves one pixel down.
- Tables are the main surface. Mono right-aligned numbers, SKU on its own line
  under the product name.
- Modals trap focus, close on Escape and return focus to the trigger.
- Empty states name the cause and the next action.
- Loading is a skeleton in the shape of what is coming.

## Do's and Don'ts

Do:

- Show the real number, with its unit and its rule.
- Put the action on the row it acts on.
- Keep every interactive element reachable by keyboard, with a visible focus
  ring.
- Respect reduced motion: no animation, no rotation of the delivery note.

Don't:

- Emoji, sparkle icons or "AI" badges. The planner is labelled by what it does.
- Eyebrow labels above headings, hero metrics, or grids of identical cards.
- Coloured left stripes on list items.
- Em dashes in interface copy.
- Purple, blue or any accent colour outside the palette above.
