# Development

Use Python 3.14 and a virtual environment. Install `cryptography` and `ruff`
for offline checks. For HA lifecycle tests use Linux with
`pytest-homeassistant-custom-component`; it resolves a compatible HA/pytest
environment. Do not install dependencies into a running HA environment.

```sh
ruff check .
python -m unittest discover -s tests -t . -v
python scripts/project.py check
python scripts/project.py package
python -m pytest tests_ha -q
```

Offline tests use a loopback fake TCP gateway and injected cloud transport.
The separate HA suite exercises config/options/reauth and entity lifecycle;
all hardware/cloud operations are mocked. CI also runs hassfest and HACS
validation. Local protocol tests deliberately bypass HA package initialization
so they need no Home Assistant installation. Do not combine the two suites
in one interpreter because of that namespace isolation.

Never put real credentials, password hashes, IDs, IPs, account records, private
profiles, APKs, screenshots or packet dumps into fixtures. Use invented values.
Public protocol constants are documented separately. Never call live cloud or
hardware during tests. New protocol commands require source evidence and
explicit physical-test coordination; do not guess command numbers.

Keep identity verification, state-race guards and bounded load management when
adding capabilities. Endpoint 0 is not a default. Automatic discovery is not
authentication. New device types require real capability evidence and tests.
Changing pagination requires source evidence plus a realistic multi-page test;
absence in an unverified snapshot must never delete devices.
