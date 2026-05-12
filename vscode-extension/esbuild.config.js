const esbuild = require('esbuild');
const watch = process.argv.includes('--watch');

(async () => {
  const ctx = await esbuild.context({
    entryPoints: ['src/extension.ts'],
    bundle: true,
    outfile: 'dist/extension.js',
    external: ['vscode'],
    platform: 'node',
    format: 'cjs',
    target: 'node18',
    sourcemap: true,
    logLevel: 'info',
  });

  if (watch) {
    await ctx.watch();
    console.log('esbuild: watching for changes...');
  } else {
    await ctx.rebuild();
    await ctx.dispose();
    console.log('esbuild: build complete');
  }
})();
