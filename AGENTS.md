# Agent guidance

This is a Nushell CLI for Mailgun domain setup and SMTP credentials. Run
`./mailgun --help` and read `README.md` before changing or using it. Tests use
`python3 -m unittest discover -s tests -v` and a loopback mock API.

Never print or copy Mailgun API keys, SMTP passwords, authentication headers,
or credential-file contents into chat, logs, commits, or shell arguments.
`./mailgun login --check` validates already configured credentials. Read-only
commands are `domains list`, `domains show`, and `smtp list`; `domains create`,
`domains verify`, and `smtp create` act on the selected account. Verify the
region and target before mutations, and proceed only within the user's request.
`domains verify` asks Mailgun to recheck DNS; no command alters DNS records.

`smtp create` writes a private credential file before contacting the API. If a
request fails or times out, do not blindly retry or delete that file: the API
may have accepted it. Inspect credential metadata and reconcile first. Do not
install credentials or change deployment configuration without authorization.
