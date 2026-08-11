import process from 'node:process';
import { Buffer } from 'node:buffer';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import yaml from '@modyfi/vite-plugin-yaml';
import svgr from 'vite-plugin-svgr';

const colorClassMapping: { [key: string]: string } = {
  '#1a1a1a': 'svg-color-bg',
  '#222': 'svg-color-bg',
  '#444': 'svg-color-inactive-cell',
  '#4dd2ff': 'svg-color-active-cell',
  '#fff': 'svg-color-text',
  '#e1ed5e': 'svg-color-text',
};

const configDirectory = path.dirname(fileURLToPath(import.meta.url));

function cyclingReviewApi(): Plugin {
  const output = path.resolve(
    configDirectory,
    'reports/cycling_review_decisions.json'
  );
  const allowedDecisions = new Set(['cycling', 'keep_running', 'unsure']);

  return {
    name: 'cycling-review-api',
    configureServer(server) {
      server.middlewares.use(
        '/api/cycling-review-decisions',
        (request, response, next) => {
          response.setHeader('Content-Type', 'application/json; charset=utf-8');

          if (request.method === 'GET') {
            if (!fs.existsSync(output)) {
              response.end(JSON.stringify({ decisions: {} }));
              return;
            }
            response.end(fs.readFileSync(output, 'utf-8'));
            return;
          }

          if (request.method !== 'POST') {
            next();
            return;
          }

          const chunks: Buffer[] = [];
          let size = 0;
          request.on('data', (chunk: Buffer) => {
            size += chunk.length;
            if (size > 1_000_000) request.destroy();
            else chunks.push(chunk);
          });
          request.on('end', () => {
            try {
              const body = JSON.parse(
                Buffer.concat(chunks).toString('utf-8')
              ) as {
                decisions?: Record<string, string>;
              };
              const entries = Object.entries(body.decisions ?? {});
              const valid = entries.every(
                ([runId, decision]) =>
                  /^\d+$/.test(runId) && allowedDecisions.has(decision)
              );
              if (!valid) throw new Error('Invalid review decision payload');

              const payload = {
                updated_at: new Date().toISOString(),
                decisions: Object.fromEntries(entries),
              };
              fs.mkdirSync(path.dirname(output), { recursive: true });
              const temporary = `${output}.tmp`;
              fs.writeFileSync(
                temporary,
                `${JSON.stringify(payload, null, 2)}\n`,
                'utf-8'
              );
              fs.renameSync(temporary, output);
              response.end(JSON.stringify({ ok: true, saved: entries.length }));
            } catch (error) {
              response.statusCode = 400;
              response.end(
                JSON.stringify({
                  ok: false,
                  error: error instanceof Error ? error.message : String(error),
                })
              );
            }
          });
        }
      );
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    cyclingReviewApi(),
    react(),
    tailwindcss(),
    yaml(),
    svgr({
      include: ['**/*.svg'],
      svgrOptions: {
        exportType: 'named',
        namedExport: 'ReactComponent',
        plugins: ['@svgr/plugin-svgo', '@svgr/plugin-jsx'],
        svgoConfig: {
          floatPrecision: 2,
          plugins: [
            {
              name: 'preset-default',
              params: {
                overrides: {
                  removeTitle: false,
                  removeViewBox: false,
                },
              },
            },
            {
              name: 'addClassesByFillColor',
              fn: () => {
                return {
                  element: {
                    enter: (node: {
                      attributes: {
                        fill?: string;
                        stroke?: string;
                        class?: string;
                      };
                    }) => {
                      const fillColor = node.attributes.fill;
                      if (fillColor) {
                        const lowerCaseFill = fillColor.toLowerCase();
                        if (colorClassMapping[lowerCaseFill]) {
                          node.attributes.class =
                            colorClassMapping[lowerCaseFill];
                        }
                      }
                      const strokeColor = node.attributes.stroke;
                      if (strokeColor) {
                        const lowerCaseStroke = strokeColor.toLowerCase();
                        if (colorClassMapping[lowerCaseStroke]) {
                          const existingClass = node.attributes.class || '';
                          const newClass = colorClassMapping[lowerCaseStroke];
                          if (!existingClass.includes(newClass)) {
                            node.attributes.class =
                              `${existingClass} ${newClass}`.trim();
                          }
                        }
                      }
                    },
                  },
                };
              },
            },
          ],
        },
      },
    }),
  ],
  base: process.env.PATH_PREFIX ? `${process.env.PATH_PREFIX}/` : '/',
  define: {
    'import.meta.env.VERCEL': JSON.stringify(process.env.VERCEL),
  },
  resolve: {
    alias: {
      '@': path.resolve(configDirectory, './src'),
      '@config': path.resolve(configDirectory, 'config.yml'),
      '@core': path.resolve(configDirectory, './src/core'),
      '@themes': path.resolve(configDirectory, './src/themes'),
      '@assets': path.resolve(configDirectory, './assets'),
    },
  },
  build: {
    manifest: true,
    modulePreload: false,
    outDir: './dist',
  },
});
