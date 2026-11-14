# ForeverTracker in a container: Apache + PHP 8.3 for the website, Python 3 and the mysql client for the analysis.
# No launcher and no setup wizard: docker/entrypoint.sh writes config.ini from the environment on every start and
# runs the first analysis by itself. See docs/DOCKER.md.
FROM php:8.3-apache-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 mariadb-client libgmp-dev libzip-dev \
 && docker-php-ext-install mysqli gmp zip \
 && apt-get purge -y --auto-remove libgmp-dev libzip-dev && apt-get install -y --no-install-recommends libgmp10 libzip4 \
 && rm -rf /var/lib/apt/lists/* \
 && a2enmod rewrite headers

COPY docker/apache.conf /etc/apache2/sites-available/000-default.conf
COPY docker/php.ini /usr/local/etc/php/conf.d/forever-tracker.ini
COPY docker/entrypoint.sh /usr/local/bin/forever-tracker-entrypoint
COPY . /opt/forever-tracker

# The commit the image was built from (--build-arg FT_COMMIT=$(git rev-parse HEAD)): kept in the COMMIT file and shown
# in the footer after the version, so a deploy can be told from the page. Empty: nothing is shown.
ARG FT_COMMIT=""

RUN chmod 755 /usr/local/bin/forever-tracker-entrypoint \
 && mkdir -p /opt/forever-tracker/data \
 && chown www-data:www-data /opt/forever-tracker/data \
 && printf '%s\n' "$FT_COMMIT" > /opt/forever-tracker/COMMIT

WORKDIR /opt/forever-tracker
# data/: client builds, Wowhead cache, logs (keep it in a volume)
VOLUME /opt/forever-tracker/data
EXPOSE 80
# The check always comes with the same session cookie: sessions are kept for a week in the data volume, and a check
# without one would leave a new session file there every 30 seconds.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD php -r 'exit(@file_get_contents("http://127.0.0.1/", false, stream_context_create(["http" => ["header" => "Cookie: ft_session=healthcheck"]])) === false ? 1 : 0);'
ENTRYPOINT ["forever-tracker-entrypoint"]
CMD ["apache2-foreground"]
