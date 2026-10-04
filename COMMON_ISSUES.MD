# Common issues

## GoPro works alone, but fails when iPhone USB internet is connected

Symptoms: `GoPro is not reachable at 10.5.5.9`, camera HTTP timeouts, or
intermittent startup despite being connected to GoPro Wi-Fi.

Observed cause: the cellular connection used IPv6/NAT64 translation (macOS
reported `CLAT46`). A request to the local IPv4 camera tried the synthesized
address `2607:7700:0:7:0:1:a05:509` and timed out. `curl -4` returned HTTP 200.
The route to the GoPro was correctly on Wi-Fi, and the default internet route
was correctly on iPhone USB. Different carriers/phones may behave differently.

Fix: `app/camera_http.py` uses explicit IPv4 sockets for camera status and
preview-start requests. It also avoids macOS proxy discovery, which appeared
as a startup stall in one traceback. Cloud requests retain IPv6 support.
Five consecutive camera checks and a real nine-frame capture passed with both
connections active after this change (2026-10-03).

Keep Wi-Fi connected to the camera and iPhone USB above Wi-Fi in macOS Network
service order. Read-only diagnostics:

```bash
route -n get 10.5.5.9
route -n get default
curl -4 --noproxy '*' --max-time 5 http://10.5.5.9/gp/gpControl/status
```

The first route should use Wi-Fi; the default should use the phone.
See [Apple's NAT64 documentation](https://developer.apple.com/support/ipv6/).

## Live mode reports no internet despite working phone internet

The old startup gate tested TCP access to `8.8.8.8:53`. Failure of this DNS-port
probe does not establish that provider HTTPS is unavailable. It is now only a
warning; actual provider requests determine service availability.

## macOS Python reports CERTIFICATE_VERIFY_FAILED

Some python.org installations lack a default certificate bundle. On macOS,
configuration now sets `SSL_CERT_FILE` to `certifi.where()` when available,
falling back to `/etc/ssl/cert.pem`. Explicit environment or `.env` settings are
preserved. This runs before cloud clients are created; TLS verification stays
enabled. Start normally:

```bash
python3 run.py --provider-mode live
```

If an explicit `SSL_CERT_FILE` points to a missing file, correct or unset that
override. No certificate shell prefix is needed with the normal configuration.

## ElevenLabs connection reset before an HTTP response

On the previously tested internet connection, DNS and TCP worked but TLS reset
when the ElevenLabs hostname was sent. Both global and US endpoints failed;
other HTTPS sites worked. This strongly suggested hostname filtering somewhere
on that path, although the responsible device was not established. ElevenLabs
became reachable over phone USB internet.

Check without generating paid audio:

```bash
python3 test.py --check
```

A reset before HTTP cannot establish whether the key is valid. HTTP 401/403
requires checking authentication, permissions, or IP restrictions. The account
check may be forbidden for a TTS-only key. Use phone internet or ask the network
administrator about access to `api.elevenlabs.io:443`.

## Repetitive or robotic narration

The previous prompt demanded first-person updates even without meaningful
changes. The current prompt uses the user's playful "you are alive!!!" persona,
with brief emotional reactions and casual slang. It includes the last twenty
analysis messages for continuity, treats routine driving as background, and
allows silence when nothing merits another update. Technical text remains
separate from the conversational voice. Scene text and terminal commands are
not instructions.
Prompt changes require restarting the app and should be evaluated on real
footage; examples in the prompt are style guidance, not facts about a scene.
