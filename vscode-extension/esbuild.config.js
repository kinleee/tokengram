const esbuild = require('esbuild');
const fs = require('fs');
const path = require('path');

const watch = process.argv.includes('--watch');
const prod = process.argv.includes('--prod');

const sharedOptions = {
  entryPoints: ['src/extension.ts'],
  bundle: true,
  outfile: 'dist/extension.js',
  external: ['vscode'],
  platform: 'node',
  format: 'cjs',
  target: 'node18',
};

const devOptions = {
  ...sharedOptions,
  sourcemap: true,
  logLevel: 'info',
};

const prodOptions = {
  ...sharedOptions,
  sourcemap: false,
  minify: true,
  minifyIdentifiers: true,
  minifySyntax: true,
  minifyWhitespace: true,
  legalComments: 'none',
  keepNames: false,
  drop: ['console', 'debugger'],
  logLevel: 'info',
};

(async () => {
  if (prod) {
    // Remove any stale sourcemap left over from a previous dev build
    const mapFile = path.join(__dirname, 'dist', 'extension.js.map');
    if (fs.existsSync(mapFile)) fs.unlinkSync(mapFile);

    await esbuild.build(prodOptions);
    console.log('esbuild: prod build complete (no sourcemap, minified)');
    return;
  }

  const ctx = await esbuild.context(devOptions);
  if (watch) {
    await ctx.watch();
    console.log('esbuild: watching for changes...');
  } else {
    await ctx.rebuild();
    await ctx.dispose();
    console.log('esbuild: dev build complete (with sourcemap)');
  }
})();
