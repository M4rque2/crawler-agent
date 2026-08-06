# Action-space smoke tasks

These are screenshot-only probes for the mobile action space. They reuse the
production system prompt, message builder, multimodal client, and tool-call
parser, but never connect to ADB or execute a device action.

Run one task:

```bash
python run_smoke_suite.py --task open_weibo --model-config model_config.json
```

Run all three once:

```bash
python run_smoke_suite.py --task all --mode quick --model-config model_config.json
```

Run qualification mode (three repetitions; each task must pass twice):

```bash
python run_smoke_suite.py --task all --mode qualify --model-config model_config.json
```

The committed PNGs were captured from the `emulator-5554` Android 15/API 35
AVD at 1080x2424. Smoke runs use only those PNGs. Reports and model traces are
written under `tasks/smoke/runs/`, which is ignored by Git.
