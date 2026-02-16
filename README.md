# Who Told Who

A daily "Who said to who" game built on the Hebrew Bible (Old Testament).


## Folder Structure

```
.
├── debug.html              # Bun-only debug entry (component playground)
├── index.html              # Bun HTML entry
├── styles.css              # UI styling
├── Taskfile.yml            # common tasks
├── package.json            # web tooling (Bun)
├── src/
│   ├── App.tsx             # app shell
│   ├── DebugPage.tsx       # debug page with component states
│   ├── debug-main.tsx      # debug entry
│   ├── main.tsx            # app entry
│   ├── types.ts            # shared types
│   ├── lib/                # helpers (format/normalize)
│   └── components/         # UI components
├── data/
│   ├── quotes/             # promoted quote dataset (legacy merged source)
│   └── quotes_options/     # chapter JSONs with inline options for the UI
```

## Source Materials

Hebrew Version:
Unicode/XML Leningrad Codex: UXLC 2.4 (27.5),
Tanach.us Inc., West Redding, CT, USA, Oct 2025.
https://tanach.us/

English Version:
TextGrid Repository (2025). English Collection. 
Multilingual Parallel Bible Corpus. Christos Christodoulopoulos. https://hdl.handle.net/21.11113/0000-0016-9447-1

Quotes were selected using Gemma3:27b.

## Quick Start

### Web dev

```
task setup
task dev
```

Main app: `http://localhost:5173/`  
Debug page: `http://localhost:5173/debug`

### Web checks

```
task check
```

### Frontend tests

```
bun run test
bun run test:e2e
```

### Quotes options loading

`src/lib/puzzleData.ts` uses a Bun Macro (`with { type: "macro" }`) to load
`data/quotes_options/*.json` via `Glob` at build/transpile time and inline the
payload into the bundle.


## License

The code in this repository is licensed under either of

```text
Apache License, Version 2.0, (LICENSE-APACHE or https://www.apache.org/licenses/LICENSE-2.0)
MIT license (LICENSE-MIT or https://opensource.org/licenses/MIT)
```

at your option.

The quotes are derived from the [Source Materials](#source-materials).
