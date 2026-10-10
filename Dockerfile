FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY server.mjs ./
COPY public ./public
# Files uploaded from Windows can arrive readable only by root; the server runs as 'node'.
RUN chmod -R a+rX /app && mkdir -p /data && chown node:node /data
ENV PORT=3000 DATA_FILE=/data/games.json
VOLUME /data
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://localhost:3000/healthz || exit 1
CMD ["node", "server.mjs"]
