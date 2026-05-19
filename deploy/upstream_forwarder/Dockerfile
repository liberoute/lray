FROM node:18-alpine

WORKDIR /app

COPY upstream_forwarder.js .
COPY dashboard.html .

ENV NODE_ENV=production

# PORT and HOST are injected at runtime by docker-compose from .env

CMD ["node", "upstream_forwarder.js"]