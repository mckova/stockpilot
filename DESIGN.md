---
name: Stockpilot
colors:
  field: "#dfe3e1"
  sage: "#bdd2c7"
  sand: "#ecdcc0"
  ink: "#17211f"
  ink-soft: "#4a5754"
  ink-faint: "#7a8683"
  pine: "#24625c"
  pine-light: "#2f7a72"
  ochre: "#9a6a1c"
  terracotta: "#b04a2e"
typography:
  sans: "Manrope Variable 300 to 800"
rounded:
  panel: 24px
  pill: 999px
---

# Stockpilot design

## Overview

Stockpilot is an operations tool for the people who run a warehouse and the
stores it feeds. The interface is calm and light: frosted panels floating on a
soft field of sage and sand, one deep green for actions, and plain tables for
the work itself. The structure is task based (Home, Planner, Products, Stock,
Purchasing, Sales, Transfers, Counts) and every action sits next to the thing it
acts on.

## Colors

- The field is a fixed radial gradient: sage and sand on a pale grey-green.
  Panels are translucent white over it.
- **Pine is the only action colour.** Primary buttons, the current nav pill,
  focus rings, key figures in a headline.
- Ochre and terracotta appear only as data: below reorder point, expiring soon,
  needs sign-off, negative variance. Never as decoration.
- Status is a word with a small dot. No tinted chips.
- No black buttons.

## Typography

- Manrope throughout, in English.
- Headlines are light (400) with the key figure in bold pine, written as a
  sentence ("2 products are below the reorder point").
- Tables: 12.5px faint headers, product names in ink at 600, numbers tabular
  and right aligned.
- Page titles are noun phrases; subtitles are one short line.

## Layout

- A pill nav on a frosted bar, sticky, with a menu for the less frequent
  screens. A badge on Planner counts proposals waiting for sign-off.
- Home is a bento of tiles: what to restock, sales, stock value and a to-do
  list. Each tile carries its own action.
- Tables sit inside a single glass panel; filters are pills above it.
- Phones keep the same composition in one column, with a scrolling nav.

## Components

- Panels: 56% white, 26px blur, white inset edge, soft shadow, 24px radius.
- Buttons are pills. Primary is pine; secondary is translucent with a pine
  outline; ghost is text.
- Icons are thin line icons (1.6 stroke).
- Modals blur the page behind them, trap focus and close on Escape.
- Proposals from the AI planner are cards with the sign-off action inside them.

## Do's and Don'ts

Do:

- Show the real number with its unit.
- Keep every interactive element reachable by keyboard, with a visible pine
  focus ring.
- Honour reduced motion and reduced transparency (panels become solid).

Don't:

- Emoji, sparkle icons or "AI" badges. The planner is named by what it does.
- Initial avatars, arrow circle buttons, grids of identical cards.
- Coloured left stripes on list items.
- Em dashes in interface copy.
- Any accent colour outside the palette above.
