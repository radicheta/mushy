FROM node:20-slim

WORKDIR /app

# Install OpenMCT (includes dist/ with JS, CSS, fonts, images) and static file server
COPY package.json ./
RUN npm install

# Expose the full dist/ tree so CSS, fonts, and workers resolve correctly
RUN cp -r node_modules/openmct/dist ./dist

# Copy plugin and custom dashboard
COPY plugins/ ./plugins/
COPY index.html ./

EXPOSE 8080

# -s: single-page app mode (rewrites 404 to index.html for OpenMCT routing)
CMD ["node_modules/.bin/serve", "-s", "-l", "8080", "."]
