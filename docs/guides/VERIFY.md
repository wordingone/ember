# Verify Ember evidence

<a id="ember.claim.public-command-set"></a>
Run public commands from the repository root at the exact source head you are reviewing. The
machine-readable replay set is
[`manifests/documentation/public-commands-v1.json`](../../manifests/documentation/public-commands-v1.json).

## Four public commands

1. Install the measured Python environment:

   ```text
   python tools/ember-restart-3b/python_environment.py install --receipt state\receipts\python-environment-install-v1.json
   ```

   Requires CPU, supported Windows Python, and network access. No GPU, credentials, data, or model
   weights are required.

2. Verify authority conservation:

   ```text
   python scripts/verify_authority_conservation.py --root .
   ```

   Requires CPU only and should report a passing authority certificate.

3. Exercise the receipt checker safely:

   ```text
   python scripts/receipt_check.py --selftest
   ```

   Requires CPU only and should emit its selftest pass sentinel.

4. Validate the public documentation system:

   ```text
   python scripts/docs_information_system.py check --root .
   ```

   Requires CPU only and should emit a JSON receipt with `result` equal to `PASS`.

These commands prove only their stated repository properties. They do not prove training,
evaluation quality, model capability, admission, or campaign completion. For the general evidence
rules, read the [reproducibility charter](../charter/REPRODUCIBILITY.md).
