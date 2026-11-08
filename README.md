# mailgun-cli

A small Nushell CLI for Mailgun sending-domain setup and SMTP credential
management. It outputs JSON and uses Mailgun's US or EU API directly. It does
not change DNS, send mail, configure a server, or deploy an application.

## Requirements

- Nushell 0.115 or newer
- OpenSSL for generating SMTP passwords
- Python 3 for the offline integration tests

Run `nix-shell` for a development shell, or run `./mailgun --help` directly.

## Authenticate

Create a private Mailgun API key in the Mailgun dashboard, then run:

```sh
./mailgun login --region us   # use eu if your sending domain is in the EU region
./mailgun login --check
```

The interactive prompt hides the key. The CLI verifies it against the domains
API before writing `${XDG_CONFIG_HOME:-~/.config}/mailgun-cli/credentials.json`
with mode `0600` in a `0700` directory. An existing credentials file is never
overwritten; move it aside securely to rotate your key. Alternatively set
`MAILGUN_API_KEY` in the environment without putting the value in your shell
history. Never pass a key as a command argument. Environment variables are
inherited by child processes, so use an appropriately scoped shell.

The stored region defaults to `us`. Override it per command with `--region us`
or `--region eu`, or set `MAILGUN_API_REGION`. Domain-specific information is
region-bound; choose the region where the sending domain is provisioned. The
CLI does not follow API redirects, and normal requests go only to Mailgun's
fixed US or EU HTTPS endpoint.

## Domains

```sh
./mailgun domains list
./mailgun domains show mg.beanledger.coffee
./mailgun domains create mg.beanledger.coffee
./mailgun domains verify mg.beanledger.coffee
```

`create` changes your Mailgun account. Inspect existing domains first. Its
response and `show` include the DNS records Mailgun returns; add the relevant
records with your DNS provider, then request verification. The CLI does not
change DNS. The list command returns one page, including `total_count`; use
`--limit` (1–1000) and `--skip` to page through results. Output is JSON; in
Nushell it can be piped to `from json`. Secret-looking response fields are
redacted. Domain creation may also provision a default SMTP login; create a
dedicated credential if you need one rather than depending on a password from
the redacted response.

## SMTP credentials

```sh
./mailgun smtp list mg.beanledger.coffee
./mailgun smtp create mg.beanledger.coffee postmaster@mg.beanledger.coffee \
  --output ~/.config/mailgun-cli/beanledger-smtp.json
```

`create` changes your Mailgun account. The output path is required, its parent
must already exist, and an existing file is never overwritten. The CLI uses
OpenSSL to generate a random password, writes the login and password to the
specified file with mode `0600` **before** making the API request, and never
prints the password. If the request fails or times out, the file is deliberately
retained: Mailgun may have accepted the request despite the failure. Inspect the
account before retrying and delete the recovery file securely if no longer
needed. `smtp list` returns metadata, not existing passwords.

The saved JSON is a local secret. Don't commit it, paste it into chat, or pass
the password through shell arguments. BeanLedger expects an SMTP URL in a
protected service environment file; its username and password must be
percent-encoded when placed in a URL. This CLI does not install that file.

API errors show the HTTP status without the response body, which might contain
sensitive information. Authentication and network errors do not print the key.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests start a loopback-only mock API with a synthetic key. They exercise actual
HTTP methods, multipart form fields, region and input validation, redaction,
private-file permissions, and recovery on failure. No real Mailgun account is
accessed. The loopback test mode refuses any key other than its synthetic key.

## API references

- [Domains](https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/domains)
- [SMTP credentials](https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/credentials)
- [US and EU endpoints](https://documentation.mailgun.com/docs/mailgun/api-reference/api-overview)
