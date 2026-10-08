# roots-review

[![tests](https://github.com/devjoinedthechat/roots-review/actions/workflows/tests.yml/badge.svg)](https://github.com/devjoinedthechat/roots-review/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python: 3.9–3.14](https://img.shields.io/badge/python-3.9%E2%80%933.14-blue.svg)](.github/workflows/tests.yml)
[![dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](#requirements)
[![MCP: stdio | HTTP](https://img.shields.io/badge/MCP-stdio%20%7C%20HTTP-blue.svg)](#connecting-a-client)

roots-review gives review agents the published Bitcoin Roots patch series over the Model Context
Protocol (MCP). Agents can read release by release, commit by commit, file by file and hunk by
hunk. They can also read the code around each change: whole functions, files as of any commit, and
the matching Bitcoin Core and Bitcoin Knots code.

Every result links to the same page in the project's patch browser, so a finding points a human
straight at something readable. Every result also carries the git command that reproduces it.

The server is read-only. It serves only patches that have been verified against their published
checksums and reproduce the tagged source tree.

## Requirements

- git 2.29 or later
- Python 3.9 or later; the standard library is all it needs
- Network access for `build` only. The first build fetches about 100 MB of git data; the server
  itself never uses the network.

## Quick start

```sh
python3 -I roots-review build           # verify and index every published release and candidate
python3 -I mcp_server.py                # serve over stdio
```

`build` lists the published Roots tags, fetches the Core and Knots base trees, downloads each
published patch, checks it against `SHA512SUMS`, replays it onto Core, and indexes the result under
`out/`. Later builds reuse what is already fetched and skip any release whose inputs have not
changed. A release that was published without a patch is reported and skipped. A checksum or
replay mismatch always stops the build.

Running `build` on a schedule, or from the release workflow, is enough to keep a hosted server current.

## Connecting a client

**stdio.** Most desktop MCP clients launch the server as a process:

```json
{
  "mcpServers": {
    "roots-review": {
      "command": "python3",
      "args": ["-I", "/path/to/roots-review/mcp_server.py"]
    }
  }
}
```

**HTTP.** Run `python3 -I mcp_server.py --http 127.0.0.1:8765` and give clients the URL
`http://127.0.0.1:8765/mcp`, or `https://<host>/mcp` when hosted (see [Hosting](#hosting)).

The server works with clients that pass `structuredContent` to the model and with clients that pass
the text content: both carry the full payload and the untrusted-content notice. It also accepts
clients that announce a newer protocol version during initialization, and negotiates a version both
sides support.

## Tools

| Tool | What it gives an agent |
|---|---|
| `list_releases` | Every release and candidate, whether it is built and verified, and its patch-browser page |
| `release_overview` | Source, integrity checks, size of the change, and what changed since the previous release (or how a port maps onto it) |
| `series_list` | Every commit in order, with author, date, size and links |
| `commit_files` | The files one commit changes, in published order, with sizes and links |
| `commit_diff` | A commit's message and diff, paged on file and hunk boundaries, with hunk ids. Optional extra context and ignore-whitespace. |
| `get_hunk` | One hunk by id: `c3.f29.h4` is commit 3, file 29, hunk 4; `n.f29.h4` is the net change against Core |
| `symbol` | The full definition of a function, method, class or struct: in the release, as of a series commit, in Core, or in Knots |
| `read_file` | Numbered lines of a file from the release, a series commit, Core, or Knots |
| `search` | git grep over any of those trees, fixed-string or POSIX regex |
| `blame` | Which series commit last changed each line, with its page |
| `file_history` | Every series commit that changes a file, with hunk ids |
| `compare_with_reference` | A file's change next to Knots' change to it, or its diff since the previous release |
| `release_delta` | The commit-by-commit difference from the previous release, or a port map across Core versions |
| `open_url` | Opens a patch-browser link (release, commit or file page) or a GitHub commit link |

Commits and files are numbered as in the published patch, which is also how the patch browser
numbers them. So `c3.f29` is `…/<release>/commit-3/file-29/`.

## Prompts and resources

The server offers four prompts, one per review job:
- **`review-release`:** review what changed since the previous release. Unchanged commits are
  skipped, modified commits are reviewed by their interdiff, and added commits are reviewed in full,
  largest first.
- **`review-port`:** check a port to a new Core version against the release it was ported from. It
  covers unported commits and the interdiff of every ported commit, separates adaptations to the new
  Core API from behaviour changes, and checks commits that are new in the port.
- **`review-commit`:** review one commit in depth.
- **`verify-finding`:** a skeptic pass that tries to disprove one finding before anyone acts on it.

Every finding is written as a claim, its location, the evidence, what would refute it, and a test
that would demonstrate it.

Each built release's data files are also available as resources at
`roots-review://{release}/{file}`: `replay.json`, `series.json`, `delta.json` and `manifest.json`.

## Trust and safety

| Property | How |
|---|---|
| Verified input | A published patch must match `SHA512SUMS`, and replaying it onto Core must reproduce the tag tree outside `.github/`. Otherwise `build` exits 3. Unreleased branches go through the same replay. |
| Read-only, closed-world | No tool writes, posts, comments, approves or merges. The server never touches the network. |
| Untrusted content | Patch text is wrapped in per-response nonce fences, and every result carries a notice to treat it as data. Text aimed at an AI reviewer is flagged. |
| Path safety | Paths are allowlisted: no `..`, no absolute paths, no pathspec magic such as `:(glob)`. git runs with literal pathspecs and a 60-second timeout. |
| Hermetic git | The user's and system git config are ignored. Hooks and credential helpers are disabled, and only https is allowed. The replay repository has no remotes, so it cannot push. |
| Protocol | Version negotiation. Requests before `initialize` are refused, ids must be strings or integers, I/O is UTF-8 at the byte level, and tool failures come back as `isError` results. |
| Deterministic output | Two forced builds produce byte-identical files. |

The checksums prove byte integrity, not authorship. Release signatures are not verified.

## Hosting

```sh
python3 -I mcp_server.py --http 127.0.0.1:8765 [--allow-origin https://example.org] [--max-concurrent 4]
```

Put a TLS reverse proxy in front and publish `https://<host>/mcp`. The HTTP transport:
- serves POST requests at `/mcp` and answers with JSON
- has no server-initiated streams: GET returns 405, and DELETE ends a session
- issues an `Mcp-Session-Id` on `initialize` and expires idle sessions after an hour
- accepts browser requests only from origins passed with `--allow-origin`
- on a loopback bind, also requires a loopback `Host` header, which blocks DNS rebinding
- limits request bodies to 1 MiB and caps concurrent tool calls with `--max-concurrent`
- never logs client addresses

The data is public, and every answer carries a `verify` command, so anyone can check a hosted answer
against their own clone.

## Configuration

`config.json` describes where the data comes from:

| Key | Meaning |
|---|---|
| `remotes` | https URLs for `core`, `knots` and `roots` |
| `patch_url`, `sums_url` | Where a release's patch and `SHA512SUMS` are published (`{release}`, `{version}`) |
| `patch_browser_url` | The patch-browser page for a release (`{release}`); commit and file pages are derived from it |
| `references` | Comparison trees for `compare_with_reference`, for example Knots `v29.3.knots20260507` against Core `v29.3` |
| `reference_by_core` | Which reference applies to a Core line: a named reference, or `release:<tag>` |
| `default_reference` | The reference for any Core line not listed in `reference_by_core` |
| `releases` | Unreleased candidates, and any release that needs settings other than the derived ones |
| `untrusted_markers` | Patterns that flag text addressed to an AI reviewer |

**A new published release needs no change**, including the first release of a new Core line.
Everything is derived from the tag name:
- **Core base:** `v30.3-roots.1` builds on Core `v30.3`.
- **Reference:** from `reference_by_core`, otherwise `default_reference`.
- **Previous release:** `v29.4-roots.5` follows `v29.4-roots.4`. The first release of a Core line
  follows the newest release of the previous line, so `v30.3-roots.1` follows `v29.4-roots.4` and
  its delta is a port map.

`roots-review discover` shows what each tag resolves to.

**An unreleased branch** is added under `releases`:

```json
"roots-30.3-candidate": {"kind": "candidate", "branch": "roots/30.3", "core_base": "v30.3",
                         "reference": "release:v29.4-roots.4", "previous": "v29.4-roots.4"}
```

## Command reference

```
roots-review build [RELEASE ...] [--force] [--offline] [--refresh] [--allow-unverified]
roots-review discover        list published Roots tags, what each resolves to, and which are built
roots-review clean [--all]   remove out/ (and the .work/ cache with --all)
```

| Option | Effect |
|---|---|
| `--force` | Rebuild even if the inputs are unchanged |
| `--offline` | Use only what is already in `.work/` |
| `--refresh` | Download published patches and checksums again |
| `--allow-unverified` | Continue past a checksum or replay mismatch; the result records that it is unverified |

Exit codes: 0 success, 2 usage or configuration error, 3 verification failure, 4 other error.

## Development

```sh
python3 -I run_tests.py            # unit tests, no network
python3 -I run_tests.py --all      # also integration tests against built data, over stdio and HTTP
ROOTS_REVIEW_DETERMINISM=1 python3 -I run_tests.py --all   # also rebuild twice and compare bytes
```

CI runs the unit tests on Python 3.9 to 3.14. It then builds every published release and candidate,
and runs the integration and determinism tests.

## Layout

```
config.json         data sources, references, releases
roots-review        command-line launcher
roots_review/       config, git (hermetic runner), workspace (fetch, verify, replay),
                    series (commit and file index), delta (range-diff, port map), diffparse, cli
mcp_server.py       the MCP server (stdio and HTTP)
prompts/            review-commit, verify-finding
tests/              unit and integration tests
out/<release>/      replay.json, series.json, delta.json, manifest.json
.work/              replay repository and downloads (a cache; safe to delete)
```

## License

MIT. See [LICENSE](LICENSE).
