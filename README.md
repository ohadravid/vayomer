# Vayómer

A daily "Who said to who" game built on the Hebrew Bible (Old Testament).

## Source Materials

Hebrew Version:

> Unicode/XML Leningrad Codex: UXLC 2.4 (27.5), \
> Tanach.us Inc., West Redding, CT, USA, Oct 2025. \
> https://tanach.us/

English Version:

> TextGrid Repository (2025). English Collection. \
> Multilingual Parallel Bible Corpus. Christos Christodoulopoulos. \
> https://hdl.handle.net/21.11113/0000-0016-9447-1

Quotes were selected using Gemma3:27b.

Code was written (mostly) by GPT-5.3-Codex.

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
npm run test
npm run test:e2e
```

### Quotes options loading

`src/lib/puzzleData.ts` uses Vite eager globs to load
`data/quotes_options/*.json` and `data/manual_quotes/*.json` (if present) via
`import.meta.glob` at build time and inline the payload into the bundle.


## License

The code in this repository is licensed under either of

```text
Apache License, Version 2.0, (LICENSE-APACHE or https://www.apache.org/licenses/LICENSE-2.0)
MIT license (LICENSE-MIT or https://opensource.org/licenses/MIT)
```

at your option.

Bundled quote-font assets in `fonts/TaameyFrankCLM.woff2` and `fonts/TaameyFrankCLM.woff` are
from Taamey Frank CLM by Yoram Gnat (via Open Siddur) and are distributed under GNU GPL v2 with
a font-embedding exception.

See the bundled license/reference files:

- `fonts/TaameyFrankCLM-LICENSE.txt`
- `fonts/TaameyFrankCLM-README.txt`

The quotes are derived from the [Source Materials](#source-materials).
