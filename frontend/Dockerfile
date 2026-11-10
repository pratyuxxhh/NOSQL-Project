FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173
# Vite dev server: hot reload and VITE_API_URL read at startup (see README, Design Decisions).
CMD ["npm", "run", "dev"]
