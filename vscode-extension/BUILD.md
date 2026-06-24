# Building & publishing the Tokengram VS Code extension

## Prerequisites (one-time)

```powershell
npm install -g @vscode/vsce
# Sign in (uses Azure DevOps PAT with Marketplace > Manage scope)
vsce login kinleee
```

## Convert icon SVG → PNG (required before first publish)

The Marketplace requires a 128×128 PNG icon. Convert `icon-source.svg` → `icon.png`:

**Option A — Inkscape (recommended):**
```powershell
inkscape icon-source.svg -w 128 -h 128 -o icon.png
```

**Option B — ImageMagick:**
```powershell
magick convert -background none icon-source.svg -resize 128x128 icon.png
```

**Option C — online:** Upload `icon-source.svg` to https://cloudconvert.com/svg-to-png and set output size 128×128.

> Replace `icon-source.svg` with a properly-designed brand asset before launch — the current SVG is a placeholder.

## Build & package locally

```powershell
npm install
npm run build:prod
vsce package           # produces tokengram-0.1.0.vsix
code --install-extension tokengram-0.1.0.vsix   # smoke-test locally
```

## Publish to Marketplace

```powershell
vsce publish           # uses version from package.json
# or bump-and-publish in one step:
vsce publish patch     # 0.1.0 → 0.1.1
vsce publish minor     # 0.1.0 → 0.2.0
```

## Checklist before `vsce publish`

- [ ] `icon.png` exists (128×128 PNG)
- [ ] `README.md` opens cleanly on github.com (Marketplace renders it the same way)
- [ ] `LICENSE.txt` reviewed by legal/founder
- [ ] `CHANGELOG.md` entry for this version
- [ ] `package.json` → `repository.url` points to a real public GitHub repo
- [ ] Tested install of the `.vsix` on a fresh VS Code profile
- [ ] Setup wizard runs end-to-end on a clean machine (no `~/.tokengram/` present)

## Cross-platform builds (Windows + Linux)

Tokengram ships **platform-specific** extensions: each `.vsix` bundles a wheel
compiled for one platform, and the Marketplace serves the right one to each
user automatically (no runtime download logic on our side).

### How the wheel is tagged

`setup.py` marks the distribution as platform-specific (`has_ext_modules()`),
so `python build_pypi.py` now produces a correctly-tagged wheel instead of the
old misleading `py3-none-any`:

| Platform | Built on | Wheel tag |
|----------|----------|-----------|
| Windows  | local (this machine) | `tokengram-X.Y.Z-cp312-cp312-win_amd64.whl` |
| Linux x64 | GitHub Actions (Ubuntu) | `tokengram-X.Y.Z-cp312-cp312-linux_x86_64.whl` |
| macOS    | not built yet (roadmap) | — |

### Windows (unchanged)

The Windows flow is exactly as documented above (`make_distribution.py` →
`build_pypi.py` → `vsce package` → `publish_release.ps1`). The only difference
is the wheel filename now carries the `cp312-cp312-win_amd64` tag.

### Linux (CI only — cannot be built on the Windows dev machine)

Cython must compile against a Linux toolchain to emit `.so` files, so the Linux
wheel + `linux-x64` VSIX are built in CI:

1. Push a `v*` tag, or run **Actions → "Build Linux artifacts" → Run workflow**.
2. The workflow ([.github/workflows/build-linux.yml](../.github/workflows/build-linux.yml))
   compiles the engine to `.so`, builds + import-verifies the Linux wheel, then
   packages `tokengram-linux-x64.vsix` (bundling only the Linux wheel).
3. Download the `tokengram-linux-x64` artifact.
4. Publish it the same way as Windows — `vsce` reads the target from the VSIX:

   ```powershell
   npx vsce publish --packagePath tokengram-linux-x64.vsix --pat $env:VSCE_PAT
   ```

### Roadmap (not blocking the first Linux release)

- **linux-arm64**: add an arch to the CI matrix (QEMU or an arm runner) and
  `vsce package --target linux-arm64`.
- **PyPI for Linux**: the wheel is tagged `linux_x86_64`, which PyPI rejects.
  Run `auditwheel repair` to produce a `manylinux` wheel before any twine
  upload. The bundled-in-VSIX install path does NOT need this (uv installs the
  wheel by file path on a matching host).
- **macOS**: build `.so`/`.dylib` on `macos-13` (Intel) + `macos-14` (Apple
  Silicon), package `darwin-x64` / `darwin-arm64`, then open the activation gate
  for `darwin` in `src/extension.ts`. Watch for Gatekeeper quarantine of the
  unsigned `.so` inside a downloaded VSIX.
