# Workbench screenshot review

After every Zepy UI change, dump `tests/renders/zepy_source.png` (GPU canvas
composited; Chrome must not use `--hide-scrollbars`) and walk this list
against the PNG. Do not call the dump clean until every item is checked.
A feature is not done if any Fail remains.

Look at each region separately: activity bar, explorer, tabs, editor,
status bar, Codex pane (transcript, status, composer). Zoom mentally on
small type. If a label is even slightly hard to read, it fails.

## Contrast and type

- [ ] Every label, tab, status chip, and tree name is readable on its
      background (no light-on-light, no gray-on-gray).
- [ ] Placeholder text is readable (chat input, search, palette).
- [ ] Typed text in inputs would be readable (light type on a dark field,
      or dark type on a light field — never light type on white).
- [ ] Disabled / muted copy is dimmer than body text but still legible.
- [ ] Syntax colors in the editor separate from the background.
- [ ] GPU editor type is as sharp as explorer/chat (HiDPI backing store;
      not a stretched 1× canvas).

## Overflow and scrollbars

- [ ] Any pane whose content is taller or wider than its box shows a
      scrollbar (explorer, SCM, chat transcript, long editor chrome).
- [ ] Scrollbars are visible in the dump (do not launch Chrome with
      `--hide-scrollbars`).
- [ ] Scrolling a pane does not clip neighboring chrome.

## Layout and overlap

- [ ] Status bar is a full-width strip; no explorer or editor text paints
      over it.
- [ ] Tabs, title, and activity bar are not covered.
- [ ] Panes have a clear split; no accidental empty black holes except the
      GPU surface while it is painting.
- [ ] The open file's tab title matches the buffer.

## Explorer and editor

- [ ] Explorer shows this repo (including `zepy/`).
- [ ] The open file is highlighted and scrolled into view.
- [ ] Editor content matches the file (no "too large" placeholder unless
      that is the file).
- [ ] Line 1 is not garbled (watch triple-quoted strings).
- [ ] Caret / current line is on a real line of that file.

## Codex pane

- [ ] Transcript is user/assistant turns, not raw tool payloads, pytest
      logs, or session ids.
- [ ] User vs Codex is visually distinct and both are readable.
- [ ] Composer placeholder "Ask Codex about this file…" is readable at a
      glance.
- [ ] Send is visible and on the composer.
- [ ] If the transcript is longer than the pane, a scrollbar is present.

## After the walk

Write Fail items explicitly. Fix them. Dump again. Repeat until this list
is all Pass.
