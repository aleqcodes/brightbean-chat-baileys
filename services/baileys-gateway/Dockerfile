FROM node:24.13.0-bookworm-slim AS build
WORKDIR /srv/gateway
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build && npm prune --omit=dev

FROM node:24.13.0-bookworm-slim
ENV NODE_ENV=production PORT=3100 BAILEYS_STATE_DIR=/var/lib/baileys
WORKDIR /srv/gateway
COPY --from=build --chown=node:node /srv/gateway/package.json ./package.json
COPY --from=build --chown=node:node /srv/gateway/node_modules ./node_modules
COPY --from=build --chown=node:node /srv/gateway/dist ./dist
RUN mkdir -p /var/lib/baileys && chown node:node /var/lib/baileys
USER node
EXPOSE 3100
STOPSIGNAL SIGTERM
CMD ["node", "dist/server.js"]
