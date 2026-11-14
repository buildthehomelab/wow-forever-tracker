# Security

Forever Tracker connects to your game databases and its Forge can write to them. Please report vulnerabilities
privately through GitHub's *Report a vulnerability* button (Security tab) rather than in a public issue.

## Recommendations

- Keep `config.ini` out of the web root (it is by default: only `public/` is served).
- Give the website a database user with only the rights it needs; without write access to `world` and `hotfixes`,
  the Forge can still preview and download SQL.
- Use long passwords for local administrators and HTTPS when the tracker is reachable from the internet.
- Set `public = 0` in `[site]` to show the tracker only to administrators.
- Failed logins are limited to 8 in 10 minutes per client address, as the web server sees it (`REMOTE_ADDR`; forwarded
  headers are not trusted). Behind a reverse proxy every visitor shares the proxy's address and therefore that limit:
  limit logins at the proxy too if it faces the internet.
- Back up your databases before applying Forge operations.
