FROM node:24-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM nginx:1.27-alpine
COPY deploy/frontend/nginx.conf /etc/nginx/conf.d/default.conf
# dist оказывается в /src (COPY frontend/ . кладёт содержимое в WORKDIR)
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
