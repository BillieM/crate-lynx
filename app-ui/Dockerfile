FROM node:20-alpine AS build

WORKDIR /srv/app-ui

COPY . /srv/app-ui

# Keep the container buildable before the React app is scaffolded.
RUN if [ -f package.json ]; then \
      if [ -f package-lock.json ]; then npm ci; else npm install; fi && \
      npm run build; \
    else \
      mkdir -p dist && \
      printf '%s\n' \
        '<!doctype html>' \
        '<html lang="en">' \
        '<head>' \
        '  <meta charset="UTF-8" />' \
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0" />' \
        '  <title>crate-lynx</title>' \
        '  <style>' \
        '    :root { color-scheme: dark; }' \
        '    body {' \
        '      margin: 0;' \
        '      min-height: 100vh;' \
        '      display: grid;' \
        '      place-items: center;' \
        '      background: #1e1e2e;' \
        '      color: #cdd6f4;' \
        '      font: 16px/1.5 sans-serif;' \
        '    }' \
        '    main {' \
        '      width: min(40rem, calc(100vw - 3rem));' \
        '      padding: 2rem;' \
        '      border: 1px solid #45475a;' \
        '      border-radius: 1rem;' \
        '      background: #181825;' \
        '      box-shadow: 0 24px 80px rgba(0, 0, 0, 0.35);' \
        '    }' \
        '    h1 { margin-top: 0; color: #89b4fa; }' \
        '    p { margin-bottom: 0; }' \
        '    code { color: #f9e2af; }' \
        '  </style>' \
        '</head>' \
        '<body>' \
        '  <main>' \
        '    <h1>crate-lynx UI scaffold</h1>' \
        '    <p>The frontend container is wired and ready. Add the Vite app in <code>app-ui/</code> and rebuild to replace this placeholder.</p>' \
        '  </main>' \
        '</body>' \
        '</html>' \
        > dist/index.html; \
    fi

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /srv/app-ui/dist /usr/share/nginx/html

EXPOSE 80
