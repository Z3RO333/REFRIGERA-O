# Usa dist pré-compilado nativamente (npm run build antes de docker buildx)
# Veja deploy.sh para o fluxo correto de build e push.
FROM nginx:alpine
COPY ./dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
