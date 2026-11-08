# Mailgun HTTP transport. Authentication is held inside Nushell, not passed
# as a subprocess argument. Do not include response bodies in errors.

export def credentials-path [] {
  let config = ($env.XDG_CONFIG_HOME? | default ($env.HOME | path join '.config'))
  $config | path join 'mailgun-cli' 'credentials.json'
}

export def base-url [region: string] {
  if $region != 'us' and $region != 'eu' { error make {msg: 'Region must be us or eu'} }
  # Loopback-only test injection. Normal use cannot redirect credentials to an
  # arbitrary endpoint, and redirect following is disabled on every request.
  if ($env.MAILGUN_TEST_MODE? | default '') == '1' {
    let base = ($env.MAILGUN_TEST_BASE_URL? | default '')
    if not ($base =~ '^http://127[.]0[.]0[.]1:[0-9]+$') {
      error make {msg: 'Test mode requires MAILGUN_TEST_BASE_URL on 127.0.0.1'}
    }
    return $base
  }
  match $region {
    'us' => 'https://api.mailgun.net'
    'eu' => 'https://api.eu.mailgun.net'
    _ => { error make {msg: 'Region must be us or eu'} }
  }
}

export def load-config [region_override: string = ''] {
  let path = (credentials-path)
  let saved = if ($path | path exists) {
    try { open $path } catch { error make {msg: 'Could not read the Mailgun credentials file'} }
  } else { {} }
  let key = ($env.MAILGUN_API_KEY? | default ($saved.api_key? | default ''))
  if ($env.MAILGUN_TEST_MODE? | default '') == '1' and $key != 'local-test-key' { error make {msg: 'Test mode accepts only the synthetic test key'} }
  let region = if $region_override != '' { $region_override } else { $env.MAILGUN_API_REGION? | default ($saved.region? | default 'us') }
  if ($key | is-empty) { error make {msg: 'No API key: run ./mailgun login or set MAILGUN_API_KEY'} }
  # Validate the region before credentials can be used.
  let base = (base-url $region)
  { api_key: $key, region: $region, base: $base }
}

export def valid-domain [domain: string] {
  let value = ($domain | str lowercase)
  if (($value | str length) > 253) or ($value | split row '.' | any {|label| ($label | str length) > 63 }) or not ($value =~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?([.][a-z0-9]([a-z0-9-]*[a-z0-9])?)+$') {
    error make {msg: 'Invalid domain name'}
  }
  $value
}

export def request [method: string, endpoint: string, body: record = {}, region: string = '', supplied_key: string = ''] {
  let config = if $supplied_key == '' { load-config $region } else { { api_key: $supplied_key, region: $region, base: (base-url $region) } }
  if ($env.MAILGUN_TEST_MODE? | default '') == '1' and $config.api_key != 'local-test-key' { error make {msg: 'Test mode accepts only the synthetic test key'} }
  let url = $config.base + $endpoint
  let auth = $"Basic (('api:' + $config.api_key) | encode base64)"
  let headers = { Authorization: $auth }
  let response = try {
    match $method {
      'GET' => { http get --full --allow-errors --redirect-mode error --max-time 30sec --headers $headers $url }
      'POST' => { http post --full --allow-errors --redirect-mode error --max-time 30sec --headers $headers --content-type 'multipart/form-data' $url $body }
      'PUT' => { http put --full --allow-errors --redirect-mode error --max-time 30sec --headers $headers $url '' }
      _ => { error make {msg: 'Unsupported HTTP method'} }
    }
  } catch { error make {msg: 'Mailgun request failed (network, TLS, or redirect error); response details suppressed'} }
  if $response.status < 200 or $response.status >= 300 {
    error make {msg: $"Mailgun request failed with HTTP ($response.status); response details suppressed"}
  }
  $response.body
}

# Avoid publishing secrets returned by the API, including in nested records.
export def redact [value: any] {
  let kind = ($value | describe)
  if ($kind | str starts-with 'record') {
    $value | transpose field item | each {|r|
      let hidden = (($r.field | str lowercase) =~ '(password|secret|api.?key|private.?key|signing.?key|token|authorization|^key$)')
      { key: $r.field, value: (if $hidden { '[redacted]' } else { redact $r.item }) }
    } | transpose -r -d
  } else if ($kind | str starts-with 'list') {
    $value | each {|item| redact $item }
  } else { $value }
}

export def show-json [value: any] { redact $value | to json --indent 2 }
