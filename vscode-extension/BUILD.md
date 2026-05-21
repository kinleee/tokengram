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
