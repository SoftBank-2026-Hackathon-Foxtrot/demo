FROM alpine:3.21
RUN apk add --no-cache pgbouncer postgresql16-client && adduser -D -H pgbouncer
COPY pgbouncer.ini userlist.txt /etc/pgbouncer/
USER pgbouncer
ENTRYPOINT ["pgbouncer", "/etc/pgbouncer/pgbouncer.ini"]
