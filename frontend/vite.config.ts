import { defineConfig } from 'vitest/config';

export default defineConfig(({ mode }) => ({
  build: {
    outDir: '../clinical/static/consultation',
    emptyOutDir: false,
    lib: { entry: 'src/mount.tsx', formats: ['es'], fileName: () => 'entry.js', cssFileName: 'consultation' },
    sourcemap: false,
  },
  define: mode === 'test' ? {} : { 'process.env.NODE_ENV': JSON.stringify('production') },
  test: { environment: 'jsdom', include: ['tests/**/*.test.tsx'] },
}));
