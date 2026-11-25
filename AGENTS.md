# Working on Query Confessional

- This repository is installable private software. Never add users' real DNS logs,
  SQLite databases, access tokens or exported inventories to Git or CI artifacts.
- Keep the runtime dependency-free unless a concrete requirement warrants a change.
  Serve assets locally; do not introduce analytics, CDN assets or domain lookups.
- Treat log content as untrusted. Use parameterized SQL, DOM text operations and
  spreadsheet-safe exports. Keep read-only API defaults and loopback binding.
- State DNS coverage honestly: queries do not prove network connections or visits.
- Preserve distinct repeated query lines. Document import identity, rotation,
  timestamp assumptions and any changes to those semantics before release.
- Use synthetic `.test`/example domains and reserved documentation IP addresses in
  tests. Run `python3 -m unittest discover -s tests -v` and
  `node --check queryconfessional/static/app.js` after implementation changes.
- Keep README installation steps and the marked guide excerpt current. Central
  CoolCode catalogue metadata should use `access: install` and the README URL;
  this tool has no scheduled public downloads or public Cloudflare data endpoint.
